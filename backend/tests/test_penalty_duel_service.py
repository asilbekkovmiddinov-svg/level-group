from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.penalty_duel import PenaltyDuelMatch, PenaltyDuelMode, PenaltyDuelRound, PenaltyDuelStatus, PenaltyDuelSubmission
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.services.penalty_duel import PenaltyDuelError, get_current_match, join_match, leaderboard_rows, match_response, process_timeout, submit_choices, utc_now
from app.services.wall_rush import get_wallet
from app.services.penalty_duel_timeouts import run_penalty_duel_timeout_worker

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, PenaltyDuelMatch.__table__, PenaltyDuelSubmission.__table__, PenaltyDuelRound.__table__, GameTicketWallet.__table__, GameTicketLedger.__table__])
    session = sessionmaker(bind=engine)()
    session.add_all([User(telegram_id=101, first_name="Asil", username="asil"), User(telegram_id=202, first_name="Jocker", username="jocker")])
    session.commit()
    try: yield session
    finally: session.close(); engine.dispose()

def _start(db, mode=PenaltyDuelMode.FREE):
    waiting = join_match(db, 101, mode); active = join_match(db, 202, mode)
    assert waiting.id == active.id
    return active

def _submit_round(db, match, p1_kick="top-left", p1_keeper="center", p2_kick="center", p2_keeper="top-right"):
    round_no = match.round_number
    match = submit_choices(db, match.id, 101, p1_kick, p1_keeper, f"p1-round-{round_no:02d}")
    return submit_choices(db, match.id, 202, p2_kick, p2_keeper, f"p2-round-{round_no:02d}")

def test_matchmaking_starts_after_second_player_and_spends_tickets_atomically(db):
    get_wallet(db, 101).game_tickets = 1; get_wallet(db, 202).game_tickets = 1; db.commit()
    waiting = join_match(db, 101, PenaltyDuelMode.TICKET)
    assert waiting.status == PenaltyDuelStatus.WAITING and db.get(GameTicketWallet, 101).game_tickets == 1
    active = join_match(db, 202, PenaltyDuelMode.TICKET)
    assert active.status == PenaltyDuelStatus.ACTIVE and active.round_deadline_at is not None
    assert db.get(GameTicketWallet, 101).game_tickets == 0 and db.get(GameTicketWallet, 202).game_tickets == 0
    assert db.query(GameTicketLedger).filter_by(operation="PENALTY_MATCH_SPEND").count() == 2

def test_first_submission_stays_hidden_until_both_players_submit(db):
    match = _start(db)
    match = submit_choices(db, match.id, 101, "top-left", "bottom-right", "hidden-choice-one")
    player_two_view = match_response(db, match, 202)
    assert player_two_view["opponent_submitted"] is True and player_two_view["history"] == [] and "kick_direction" not in player_two_view
    resolved = submit_choices(db, match.id, 202, "center", "top-right", "hidden-choice-two")
    view = match_response(db, resolved, 101)
    assert view["round_number"] == 2 and view["your_score"] == 1 and view["opponent_score"] == 1
    assert view["history"][0]["your_kick"] == "top-left" and view["history"][0]["opponent_keeper"] == "top-right"

def test_five_rounds_finish_and_reward_tournament_ticket_exactly_once(db):
    get_wallet(db, 101).game_tickets = 1; get_wallet(db, 202).game_tickets = 1; db.commit(); match = _start(db, PenaltyDuelMode.TICKET)
    for _ in range(5): match = _submit_round(db, match)
    assert match.status == PenaltyDuelStatus.FINISHED and match.winner_id == 101 and match.player_one_score == 5 and match.player_two_score == 0
    assert match.reward_granted is True and db.get(GameTicketWallet, 101).tournament_tickets == 1
    assert db.query(GameTicketLedger).filter_by(operation="PENALTY_WIN_REWARD").count() == 1 and get_current_match(db, 202).id == match.id
    duplicate = submit_choices(db, match.id, 202, "center", "top-right", "p2-round-05")
    assert duplicate.id == match.id and db.get(GameTicketWallet, 101).tournament_tickets == 1

def test_leaderboards_are_mode_specific_and_losses_do_not_reduce_rating(db):
    free_match = _start(db, PenaltyDuelMode.FREE)
    for _ in range(5): free_match = _submit_round(db, free_match)
    free_rows = leaderboard_rows(db, PenaltyDuelMode.FREE)
    assert [row["telegram_id"] for row in free_rows] == [101, 202]
    assert free_rows[0] == {"rank": 1, "telegram_id": 101, "display_name": "Asil", "username": "asil", "played": 1, "wins": 1, "losses": 0, "rating": 1025}
    assert free_rows[1]["rating"] == 1000 and leaderboard_rows(db, PenaltyDuelMode.TICKET) == []

def test_tied_regulation_enters_sudden_death_until_score_differs(db):
    match = _start(db)
    for _ in range(5): match = _submit_round(db, match, p1_kick="center", p1_keeper="center", p2_kick="center", p2_keeper="center")
    assert match.status == PenaltyDuelStatus.ACTIVE and match.round_number == 6 and match_response(db, match, 101)["sudden_death"] is True
    match = _submit_round(db, match)
    assert match.status == PenaltyDuelStatus.FINISHED and match.winner_id == 101

def test_no_response_timeout_refunds_both_ticket_entries(db):
    get_wallet(db, 101).game_tickets = 1; get_wallet(db, 202).game_tickets = 1; db.commit(); match = _start(db, PenaltyDuelMode.TICKET)
    match.round_deadline_at = utc_now() - timedelta(seconds=1); db.commit(); cancelled = process_timeout(db, match.id, 101)
    assert cancelled.status == PenaltyDuelStatus.CANCELLED and db.get(GameTicketWallet, 101).game_tickets == 1 and db.get(GameTicketWallet, 202).game_tickets == 1
    assert db.query(GameTicketLedger).filter_by(operation="PENALTY_MATCH_REFUND").count() == 2

def test_single_submitter_wins_on_timeout(db):
    match = _start(db); match = submit_choices(db, match.id, 101, "top-left", "center", "timeout-submit-one")
    match.round_deadline_at = utc_now() - timedelta(seconds=1); db.commit(); finished = process_timeout(db, match.id, 202)
    assert finished.status == PenaltyDuelStatus.FINISHED and finished.winner_id == 101

def test_duplicate_submission_is_idempotent_and_second_choice_same_round_is_ignored(db):
    match = _start(db); match = submit_choices(db, match.id, 101, "center", "center", "parallel-submit-one")
    duplicate = submit_choices(db, match.id, 101, "center", "center", "parallel-submit-one")
    assert duplicate.id == match.id
    second = submit_choices(db, match.id, 101, "top-left", "top-left", "second-choice-same-round")
    assert second.id == match.id
    assert db.query(PenaltyDuelSubmission).filter_by(match_id=match.id, round_number=1, player_id=101).count() == 1

def test_expired_abandoned_match_is_settled_before_new_queue_entry(db):
    match = _start(db); match.round_deadline_at = utc_now() - timedelta(seconds=1); db.commit(); replacement = join_match(db, 101, PenaltyDuelMode.FREE)
    assert match.status == PenaltyDuelStatus.CANCELLED and replacement.id != match.id and replacement.status == PenaltyDuelStatus.WAITING

def test_background_worker_cancels_due_match_without_connected_clients(db):
    match = _start(db); now = utc_now(); match.round_deadline_at = now - timedelta(seconds=1); db.commit()
    result = run_penalty_duel_timeout_worker(db, now=now); db.refresh(match)
    assert result.scanned == 1 and result.processed == 1 and result.failed == 0 and match.status == PenaltyDuelStatus.CANCELLED

def test_background_worker_awards_forfeit_to_only_submitter(db):
    match = _start(db); match = submit_choices(db, match.id, 101, "top-left", "center", "worker-timeout-submit")
    now = utc_now(); match.round_deadline_at = now - timedelta(seconds=1); db.commit(); result = run_penalty_duel_timeout_worker(db, now=now); db.refresh(match)
    assert result.processed == 1 and match.status == PenaltyDuelStatus.FINISHED and match.winner_id == 101

def test_background_worker_ignores_future_deadlines(db):
    match = _start(db); now = utc_now(); match.round_deadline_at = now + timedelta(seconds=10); db.commit(); result = run_penalty_duel_timeout_worker(db, now=now)
    assert result.scanned == 0 and result.processed == 0 and match.status == PenaltyDuelStatus.ACTIVE
