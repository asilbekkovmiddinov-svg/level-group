from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.services.penalty_duel_ads import (
    PenaltyDuelAdError, grant_penalty_duel_ad_ticket,
)


def test_penalty_ad_rotation_is_global_idempotent_and_separate_from_wall_rush():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__, GameTicketWallet.__table__, GameTicketLedger.__table__,
    ])
    db = sessionmaker(bind=engine)()
    db.add(User(telegram_id=808, first_name="Rotation User"))
    db.commit()
    now = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
    try:
        wallet = grant_penalty_duel_ad_ticket(
            db, 808, "ADSGRAM", "adsgram-event-001", now=now,
        )
        assert wallet.game_tickets == 1
        assert wallet.penalty_duel_rewarded_ad_provider_index == 1
        assert wallet.last_rewarded_ad_at is None

        replay = grant_penalty_duel_ad_ticket(
            db, 808, "ADSGRAM", "adsgram-event-001", now=now,
        )
        assert replay.game_tickets == 1

        with pytest.raises(PenaltyDuelAdError, match="once per 5 minutes"):
            grant_penalty_duel_ad_ticket(
                db, 808, "TADS", "tads-event-0001",
                now=now + timedelta(minutes=4, seconds=59),
            )
        db.rollback()

        wallet = grant_penalty_duel_ad_ticket(
            db, 808, "TADS", "tads-event-0002", now=now + timedelta(minutes=5),
        )
        assert wallet.game_tickets == 2
        assert wallet.penalty_duel_rewarded_ad_provider_index == 2
        assert db.query(GameTicketLedger).filter_by(
            operation="PENALTY_AD_GRANT",
        ).count() == 2
    finally:
        db.close()
        engine.dispose()
