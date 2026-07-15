from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.crud import match as match_crud
from app.models.match import Match, MatchStatus
from app.models.user import User


NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[User.__table__, Match.__table__])
    session = sessionmaker(bind=engine)()
    session.add(User(telegram_id=1001, first_name="Arena open-list test"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _match(*, status: MatchStatus, deadline: datetime | None, scheduled_offset: int) -> Match:
    stake = Decimal("100")
    return Match(
        creator_telegram_id=1001,
        efc_amount=stake,
        total_pool=stake * 2,
        commission_amount=Decimal("10"),
        winner_reward=Decimal("190"),
        status=status,
        scheduled_at=NOW + timedelta(minutes=scheduled_offset),
        timeout_deadline_at=deadline,
    )


def test_open_matches_excludes_expired_and_cancelled_rows(db, monkeypatch):
    future = _match(
        status=MatchStatus.WAITING_PLAYER,
        deadline=NOW + timedelta(minutes=5),
        scheduled_offset=5,
    )
    expired = _match(
        status=MatchStatus.WAITING_PLAYER,
        deadline=NOW - timedelta(seconds=1),
        scheduled_offset=-1,
    )
    cancelled = _match(
        status=MatchStatus.CANCELLED,
        deadline=None,
        scheduled_offset=1,
    )
    legacy_without_deadline = _match(
        status=MatchStatus.WAITING_PLAYER,
        deadline=None,
        scheduled_offset=2,
    )
    db.add_all([future, expired, cancelled, legacy_without_deadline])
    db.commit()
    monkeypatch.setattr(match_crud, "utc_now", lambda: NOW)

    result = match_crud.get_open_matches(db)

    assert [match.id for match in result] == [legacy_without_deadline.id, future.id]
    assert expired.id not in {match.id for match in result}
    assert cancelled.id not in {match.id for match in result}
