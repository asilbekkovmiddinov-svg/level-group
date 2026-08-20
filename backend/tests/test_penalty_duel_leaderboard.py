from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.penalty_duel import PenaltyDuelMatch, PenaltyDuelMode, PenaltyDuelStatus
from app.models.user import User
from app.services.penalty_duel_leaderboard import leaderboard_rows, weekly_period_end, weekly_period_start


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[User.__table__, PenaltyDuelMatch.__table__])
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(telegram_id=101, first_name="Asil"),
        User(telegram_id=202, first_name="Jocker"),
        User(telegram_id=303, first_name="Player"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _finished(db, match_id, mode, player_one, player_two, winner, finished_at):
    db.add(PenaltyDuelMatch(
        id=match_id,
        mode=mode,
        status=PenaltyDuelStatus.FINISHED,
        player_one_id=player_one,
        player_two_id=player_two,
        winner_id=winner,
        player_one_score=3 if winner == player_one else 1,
        player_two_score=3 if winner == player_two else 1,
        round_number=10,
        finished_at=finished_at,
    ))
    db.commit()


def test_week_starts_on_tashkent_monday():
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    assert weekly_period_start(now) == datetime(2026, 8, 16, 19, 0, tzinfo=timezone.utc)
    assert weekly_period_end(now) == datetime(2026, 8, 23, 19, 0, tzinfo=timezone.utc)


def test_weekly_order_and_overall_rating_are_returned_per_mode(db):
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    previous_week = datetime(2026, 8, 16, 18, 0, tzinfo=timezone.utc)
    current_week = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    _finished(db, "free-old", PenaltyDuelMode.FREE, 101, 202, 101, previous_week)
    _finished(db, "free-one", PenaltyDuelMode.FREE, 101, 202, 202, current_week)
    _finished(db, "free-two", PenaltyDuelMode.FREE, 202, 303, 202, current_week)
    _finished(db, "ticket-one", PenaltyDuelMode.TICKET, 101, 303, 303, current_week)

    free = leaderboard_rows(db, PenaltyDuelMode.FREE, now=now)
    assert [row["telegram_id"] for row in free] == [202, 101, 303]
    assert free[0]["weekly_rating"] == 1050
    assert free[0]["weekly_wins"] == 2
    assert free[0]["overall_rating"] == 1050
    assert free[1]["weekly_rating"] == 1000
    assert free[1]["overall_rating"] == 1025
    assert free[1]["overall_wins"] == 1

    ticket = leaderboard_rows(db, PenaltyDuelMode.TICKET, now=now)
    assert [row["telegram_id"] for row in ticket] == [303, 101]
    assert ticket[0]["weekly_rating"] == 1025
    assert ticket[0]["overall_rating"] == 1025
