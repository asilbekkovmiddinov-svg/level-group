from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.user import User
from app.models.wall_rush import (
    GameTicketLedger, GameTicketWallet, WallRushAction, WallRushMatch,
    WallRushMode, WallRushStatus,
)
from app.services.wall_rush import (
    WallRushError, cancel_waiting_match, get_wallet, grant_ad_ticket, join_match, leaderboard_rows, process_timeout,
    submit_action, utc_now,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__, WallRushMatch.__table__, WallRushAction.__table__,
        GameTicketWallet.__table__, GameTicketLedger.__table__,
    ])
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(telegram_id=101, first_name="Red"),
        User(telegram_id=202, first_name="Blue"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_free_matchmaking_starts_only_when_opponent_arrives(db):
    waiting = join_match(db, 101, WallRushMode.FREE)
    assert waiting.status == WallRushStatus.WAITING
    assert waiting.blue_player_id is None

    active = join_match(db, 202, WallRushMode.FREE)
    assert active.id == waiting.id
    assert active.status == WallRushStatus.ACTIVE
    assert active.current_turn_player_id == 101
    assert active.turn_deadline_at is not None


def test_ticket_is_spent_only_after_both_players_match(db):
    get_wallet(db, 101).game_tickets = 1
    get_wallet(db, 202).game_tickets = 1
    db.commit()

    join_match(db, 101, WallRushMode.TICKET)
    assert db.get(GameTicketWallet, 101).game_tickets == 1
    match = join_match(db, 202, WallRushMode.TICKET)

    assert db.get(GameTicketWallet, 101).game_tickets == 0
    assert db.get(GameTicketWallet, 202).game_tickets == 0
    assert db.query(GameTicketLedger).filter_by(operation="MATCH_SPEND").count() == 2
    assert match.status == WallRushStatus.ACTIVE


def test_ticket_match_does_not_start_if_either_wallet_is_empty(db):
    get_wallet(db, 101).game_tickets = 1
    db.commit()
    join_match(db, 101, WallRushMode.TICKET)

    with pytest.raises(WallRushError, match="One Game Ticket"):
        join_match(db, 202, WallRushMode.TICKET)
    db.rollback()
    assert db.get(GameTicketWallet, 101).game_tickets == 1


def test_action_is_authoritative_versioned_and_idempotent(db):
    match = join_match(db, 101, WallRushMode.FREE)
    match = join_match(db, 202, WallRushMode.FREE)

    moved = submit_action(
        db, match.id, 101, "MOVE", 11, 2, None,
        match.version, "move-red-0001",
    )
    assert (moved.red_row, moved.red_column) == (11, 2)
    assert moved.current_turn_player_id == 202

    duplicate = submit_action(
        db, match.id, 101, "MOVE", 11, 2, None,
        match.version, "move-red-0001",
    )
    assert duplicate.version == moved.version
    assert db.query(WallRushAction).count() == 1

    with pytest.raises(WallRushError, match="not this player's turn"):
        submit_action(
            db, match.id, 101, "MOVE", 10, 2, None,
            moved.version, "move-red-0002",
        )


def test_third_missed_turn_finishes_match(db):
    match = join_match(db, 101, WallRushMode.FREE)
    match = join_match(db, 202, WallRushMode.FREE)
    match.red_missed_turns = 2
    match.turn_deadline_at = utc_now() - timedelta(seconds=1)
    db.commit()

    finished = process_timeout(db, match.id, 202)
    assert finished.status == WallRushStatus.FINISHED
    assert finished.winner_id == 202
    assert finished.red_missed_turns == 3


def test_ticket_winner_receives_one_tournament_ticket_once(db):
    get_wallet(db, 101).game_tickets = 1
    get_wallet(db, 202).game_tickets = 1
    db.commit()
    join_match(db, 101, WallRushMode.TICKET)
    match = join_match(db, 202, WallRushMode.TICKET)
    match.red_row = 1
    match.red_column = 2
    db.commit()

    finished = submit_action(
        db, match.id, 101, "MOVE", 0, 2, None,
        match.version, "winning-move-0001",
    )
    assert finished.winner_id == 101
    assert db.get(GameTicketWallet, 101).tournament_tickets == 1
    assert db.query(GameTicketLedger).filter_by(operation="WIN_REWARD").count() == 1


def test_verified_ad_event_has_30_minute_cooldown_and_is_idempotent(db):
    now = utc_now()
    wallet = grant_ad_ticket(db, 101, "provider-event-1", now)
    assert wallet.game_tickets == 1
    assert grant_ad_ticket(db, 101, "provider-event-1", now).game_tickets == 1

    with pytest.raises(WallRushError, match="once per 30 minutes"):
        grant_ad_ticket(db, 101, "provider-event-2", now + timedelta(minutes=29))
    db.rollback()

    wallet = grant_ad_ticket(db, 101, "provider-event-3", now + timedelta(minutes=30))
    assert wallet.game_tickets == 2


def test_ticket_queue_requires_ticket_before_search_starts(db):
    with pytest.raises(WallRushError, match="One Game Ticket"):
        join_match(db, 101, WallRushMode.TICKET)
    db.rollback()
    assert db.query(WallRushMatch).filter_by(red_player_id=101).count() == 0


def test_waiting_player_can_cancel_without_spending_ticket(db):
    get_wallet(db, 101).game_tickets = 1
    db.commit()
    waiting = join_match(db, 101, WallRushMode.TICKET)
    cancelled = cancel_waiting_match(db, waiting.id, 101)
    assert cancelled.status == WallRushStatus.CANCELLED
    assert db.get(GameTicketWallet, 101).game_tickets == 1
    assert join_match(db, 101, WallRushMode.FREE).status == WallRushStatus.WAITING



def test_leaderboards_are_separate_and_include_played_wins_losses(db):
    db.add_all([
        WallRushMatch(
            id="free-one", mode=WallRushMode.FREE, status=WallRushStatus.FINISHED,
            red_player_id=101, blue_player_id=202, winner_id=101, walls=[],
        ),
        WallRushMatch(
            id="free-two", mode=WallRushMode.FREE, status=WallRushStatus.FINISHED,
            red_player_id=202, blue_player_id=101, winner_id=101, walls=[],
        ),
        WallRushMatch(
            id="ticket-one", mode=WallRushMode.TICKET, status=WallRushStatus.FINISHED,
            red_player_id=101, blue_player_id=202, winner_id=202, walls=[],
        ),
    ])
    db.commit()

    free = leaderboard_rows(db, WallRushMode.FREE)
    ticket = leaderboard_rows(db, WallRushMode.TICKET)

    assert [(row["telegram_id"], row["played"], row["wins"], row["losses"]) for row in free] == [
        (101, 2, 2, 0),
        (202, 2, 0, 2),
    ]
    assert [(row["telegram_id"], row["played"], row["wins"], row["losses"]) for row in ticket] == [
        (202, 1, 1, 0),
        (101, 1, 0, 1),
    ]
    assert [row["rank"] for row in free] == [1, 2]
