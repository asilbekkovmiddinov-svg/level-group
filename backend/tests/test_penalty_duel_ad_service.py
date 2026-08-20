from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config
from app.core.database import Base
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.services.penalty_duel_ads import (
    PenaltyDuelAdError, grant_penalty_duel_ad_ticket,
)


def test_penalty_ad_rotation_is_global_idempotent_and_separate_from_wall_rush(monkeypatch):
    monkeypatch.setattr(config, "ONCLICKA_REWARDED_AD_ENABLED", False)
    monkeypatch.setattr(config, "TADS_WEBHOOK_SECRET", "tads-secret")
    monkeypatch.setattr(config, "TADS_WALL_RUSH_WIDGET_ID", "11416")
    monkeypatch.setattr(config, "TELEGA_REWARD_SECRET", "telega-secret")
    monkeypatch.setattr(config, "TELEGA_MINIAPP_TOKEN", "telega-token")
    monkeypatch.setattr(config, "TELEGA_REWARDED_AD_BLOCK_UUID", "telega-block")
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
        wallet = grant_penalty_duel_ad_ticket(
            db, 808, "TELEGA", "telega-event-0001", now=now + timedelta(minutes=10),
        )
        assert wallet.game_tickets == 3
        assert wallet.penalty_duel_rewarded_ad_provider_index == 0
        assert db.query(GameTicketLedger).filter_by(
            operation="PENALTY_AD_GRANT",
        ).count() == 3
    finally:
        db.close()
        engine.dispose()


def test_onclicka_provider_requires_complete_feature_configuration(monkeypatch):
    monkeypatch.setattr(config, "ONCLICKA_REWARDED_AD_ENABLED", False)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__, GameTicketWallet.__table__, GameTicketLedger.__table__,
    ])
    db = sessionmaker(bind=engine)()
    db.add(User(telegram_id=809, first_name="Optional Provider User"))
    db.commit()
    now = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
    try:
        with pytest.raises(PenaltyDuelAdError, match="disabled"):
            grant_penalty_duel_ad_ticket(
                db, 809, "ONCLICKA", "disabled-event", now=now,
            )
        db.rollback()

        monkeypatch.setattr(config, "ONCLICKA_REWARDED_AD_ENABLED", True)
        monkeypatch.setattr(
            config, "ONCLICKA_REWARD_SECRET", "enabled-token-0123456789abcdef0123456789",
        )
        monkeypatch.setattr(config, "ONCLICKA_SPOT_ID", "6131849")
        wallet = grant_penalty_duel_ad_ticket(
            db, 809, "ONCLICKA", "enabled-event", now=now,
        )
        assert wallet.game_tickets == 1
        assert wallet.penalty_duel_rewarded_ad_provider_index == 0
    finally:
        db.close()
        engine.dispose()
