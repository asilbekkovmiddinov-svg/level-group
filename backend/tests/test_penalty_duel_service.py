from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.penalty_duel import (
    PenaltyDuelMatch,
    PenaltyDuelMode,
    PenaltyDuelRound,
    PenaltyDuelStatus,
    PenaltyDuelSubmission,
)
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.services.penalty_duel import (
    PenaltyDuelError,
    get_current_match,
    join_match,
    match_response,
    process_timeout,
    submit_choices,
    utc_now,
)
from app.services.wall_rush import get_wallet
from app.services.penalty_duel_timeouts import run_penalty_duel_timeout_worker


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__,
        PenaltyDuelMatch.__table__,
        PenaltyDuelSubmission.__table__,
        PenaltyDuelRound.__table__,
        GameTicketWallet.__table__,
        GameTicketLedger.__table__,
    ])
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(telegram_id=101, first_name="Asil", username="asil"),
        User(telegram_id=202, first_name="Jocker", username="jocker"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _start(db, mode=PenaltyDuelMode.FREE):
    waiting = join_match(db, 101, mode)
    active = join_match(db, 202, mode)
    assert waiting.id == active.id
    return active


def _submit_round(db, match, p1_kick="top-left", p1_keeper="center", p2_kick="center", p2_keeper="top-right"):
    match = submit_choices(
        db,
        match.id,
        101,
        p1_kick,
        p1_keeper,
        match.version,
        f"p1-round-{match.round_number:02d}",
    )
    return submit_choices(
        db,
        match.id,
        202,
        p2_kick,
        p2_keeper,
        match.version,
        f"p2-round-{match.round_number:02d}",
    )


def test_matchmaking_starts_after_second_player_and_spends_tickets_atomically(db):
    get_wallet(db, 101).game_tickets = 1
    get_wallet(db, 202).game_tickets = 1
    db.commit()

    waiting = join_match(db, 101, PenaltyDuelMode.TICKET)
    assert waiting.status == PenaltyDuelStatus.WAITING
    assert db.get(GameTicketWallet, 101).game_tickets == 1

    active = join_match(db, 202, PenaltyDuelMode.TICKET)
    assert active.status == PenaltyDuelStatus.ACTIVE
    assert active.round_deadline_at is not None
    assert db.get(GameTicketWallet, 101).game_tickets == 0
    assert db.get(GameTicketWallet, 202).game_tickets == 0
    assert db.query(GameTicketLedger).filter_by(operation="PENALTY_MATCH_SPEND").count() == 2


def test_first_submission_stays_hidden_until_both_players_submit(db):
    match = _start(db)
    match = submit_choices(
        db,
        match.id,
        101,
        "top-left",
        "bottom-right",
        match.version,
        "hidden-choice-one",
    )

    player_two_view = match_response(db, match, 202)
    assert player_two_view["opponent_submitted"] is True
    assert player_two_view["history"] == []
    assert "kick_direction" not in player_two_view

    resolved = submit_choices(
        db,
        match.id,
        202,
        "center",
        "top-right",
        match.version,
        "hidden-choice-two",
    )
    view = match_response(db, resolved, 101)
    assert view["round_number"] == 2
    assert view["your_score"] == 1
    assert view["opponent_score"] == 1
    assert view["history"][0]["your_kick"] == "top-left"
    assert view["history"][0]["opponent_keeper"] == "top-right"


def test_five_rounds_finish_and_reward_tournament_ticket_exactly_once(db):
    get_wallet(db, 101).game_tickets = 1
    get_wallet(db, 202).game_tickets = 1
    db.commit()
    match = _start(db, PenaltyDuelMode.TICKET)

    for _ in range(5):
        match = _submit_round(db, match)

    assert match.status == PenaltyDuelStatus.FINISHED
    assert match.winner_id == 101
    assert match.player_one_score == 5
    assert match.player_two_score == 0
    assert match.reward_granted is True
    assert db.get(GameTicketWallet, 101).tournament_tickets == 1
    assert db.query(GameTicketLedger).filter_by(operation="PENALTY_WIN_REWARD").count() == 1
    assert get_current_match(db, 202).id == match.id

    duplicate = submit_choices(
        db,
        match.id,
        202,
        "center",
        "center",
        match.version - 1,
        "p2-round-05",
    )
    assert duplicate.id == match.id
    assert db.get(GameTicketWallet, 101).tournament_tickets == 1


def test_tied_regulation_enters_sudden_death_until_score_differs(db):
    match = _start(db)
    for _ in range(5):
        match = _submit_round(
            db,
            match,
            p1_kick="center",
            p1_keeper="center",
            p2_kick="center",
            p2_keeper="center",
        )

    assert match.status == PenaltyDuelStatus.ACTIVE
    assert match.round_number == 6
    assert match_response(db, match, 101)["sudden_death"] is True

    match = _submit_round(db, match)
    assert match.status == PenaltyDuelStatus.FINISHED
    assert match.winner_id == 101


def test_no_response_timeout_refunds_both_ticket_entries(db):
    get_wallet(db, 101).game_tickets = 1
    get_wallet(db, 202).game_tickets = 1
    db.commit()
    match = _start(db, PenaltyDuelMode.TICKET)
    match.round_deadline_at = utc_now() - timedelta(seconds=1)
    db.commit()

    cancelled = process_timeout(db, match.id, 101)
    assert cancelled.status == PenaltyDuelStatus.CANCELLED
    assert db.get(GameTicketWallet, 101).game_tickets == 1
    assert db.get(GameTicketWallet, 202).game_tickets == 1
    assert db.query(GameTicketLedger).filter_by(operation="PENALTY_MATCH_REFUND").count() == 2


def test_single_submitter_wins_on_timeout(db):
    match = _start(db)
    match = submit_choices(
        db,
        match.id,
        101,
        "top-left",
        "center",
        match.version,
        "timeout-submit-one",
    )
    match.round_deadline_at = utc_now() - timedelta(seconds=1)
    db.commit()

    finished = process_timeout(db, match.id, 202)
    assert finished.status == PenaltyDuelStatus.FINISHED
    assert finished.winner_id == 101


def test_stale_parallel_and_duplicate_round_submissions_are_rejected(db):
    match = _start(db)
    initial_version = match.version
    match = submit_choices(
        db,
        match.id,
        101,
        "center",
        "center",
        initial_version,
        "parallel-submit-one",
    )
    with pytest.raises(PenaltyDuelError, match="version is stale"):
        submit_choices(
            db,
            match.id,
            202,
            "center",
            "center",
            initial_version,
            "parallel-submit-two",
        )
    db.rollback()

    with pytest.raises(PenaltyDuelError, match="already submitted"):
        submit_choices(
            db,
            match.id,
            101,
            "top-left",
            "top-left",
            match.version,
            "second-choice-same-round",
        )


def test_expired_abandoned_match_is_settled_before_new_queue_entry(db):
    match = _start(db)
    match.round_deadline_at = utc_now() - timedelta(seconds=1)
    db.commit()

    replacement = join_match(db, 101, PenaltyDuelMode.FREE)
    assert match.status == PenaltyDuelStatus.CANCELLED
    assert replacement.id != match.id
    assert replacement.status == PenaltyDuelStatus.WAITING


def test_background_worker_cancels_due_match_without_connected_clients(db):
    match = _start(db)
    now = utc_now()
    match.round_deadline_at = now - timedelta(seconds=1)
    db.commit()

    result = run_penalty_duel_timeout_worker(db, now=now)
    db.refresh(match)
    assert result.scanned == 1
    assert result.processed == 1
    assert result.failed == 0
    assert match.status == PenaltyDuelStatus.CANCELLED


def test_background_worker_awards_forfeit_to_only_submitter(db):
    match = _start(db)
    match = submit_choices(
        db,
        match.id,
        101,
        "top-left",
        "center",
        match.version,
        "worker-timeout-submit",
    )
    now = utc_now()
    match.round_deadline_at = now - timedelta(seconds=1)
    db.commit()

    result = run_penalty_duel_timeout_worker(db, now=now)
    db.refresh(match)
    assert result.processed == 1
    assert match.status == PenaltyDuelStatus.FINISHED
    assert match.winner_id == 101


def test_background_worker_ignores_future_deadlines(db):
    match = _start(db)
    now = utc_now()
    match.round_deadline_at = now + timedelta(seconds=10)
    db.commit()

    result = run_penalty_duel_timeout_worker(db, now=now)
    assert result.scanned == 0
    assert result.processed == 0
    assert match.status == PenaltyDuelStatus.ACTIVE
