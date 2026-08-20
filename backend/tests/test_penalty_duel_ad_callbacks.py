from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config
from app.core.database import Base, get_db
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet, WallRushMatch
from app.models.wheel import AdsgramRewardSession
from app.routers.penalty_duel_ads import router
from app.services import adsgram_reward


ONCLICKA_TOKEN = "onclicka-opaque-token-0123456789abcdef"


def build(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__, WallRushMatch.__table__, GameTicketWallet.__table__,
        GameTicketLedger.__table__, AdsgramRewardSession.__table__,
    ])
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(User(telegram_id=707, first_name="Reward User"))
        db.commit()

    monkeypatch.setattr(config, "TELEGA_REWARD_SECRET", "telega-secret")
    monkeypatch.setattr(
        config, "TELEGA_REWARDED_AD_BLOCK_UUID",
        "626b9d82-89c5-4e08-b6d4-9fc8bdc2f486",
    )
    monkeypatch.setattr(config, "ONCLICKA_REWARD_SECRET", ONCLICKA_TOKEN)
    monkeypatch.setattr(config, "TADS_WEBHOOK_SECRET", "tads-secret")
    monkeypatch.setattr(config, "TADS_WALL_RUSH_WIDGET_ID", "11416")

    app = FastAPI()
    app.include_router(router)

    def dependency():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    return TestClient(app), sessions, engine


def test_telega_callback_requires_secret_and_rotates_after_verified_view(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        path = "/penalty-duel/rewards/telega/callback"
        rejected = client.get(path, params={
            "USERID": 707,
            "ad_block_uuid": "626b9d82-89c5-4e08-b6d4-9fc8bdc2f486",
        })
        assert rejected.status_code == 401

        rewarded = client.get(path, params={
            "secret": "telega-secret",
            "USERID": 707,
            "event_id": "telega-view-0001",
            "ad_block_uuid": "626b9d82-89c5-4e08-b6d4-9fc8bdc2f486",
        })
        assert rewarded.status_code == 200
        assert rewarded.json()["rewarded"] is True
        assert (
            rewarded.json()["wallet"]["next_penalty_duel_rewarded_ad_provider"]
            == "ONCLICKA"
        )

        duplicate = client.get(path, params={
            "secret": "telega-secret",
            "USERID": 707,
            "event_id": "telega-view-0001",
            "ad_block_uuid": "626b9d82-89c5-4e08-b6d4-9fc8bdc2f486",
        })
        assert duplicate.status_code == 200
        with sessions() as db:
            assert db.get(GameTicketWallet, 707).game_tickets == 1
            assert db.query(GameTicketLedger).filter_by(operation="PENALTY_AD_GRANT").count() == 1
    finally:
        engine.dispose()


def test_onclicka_callback_shares_cooldown_and_returns_rotation_to_adsgram(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        with sessions() as db:
            wallet = GameTicketWallet(
                telegram_id=707,
                game_tickets=1,
                last_penalty_duel_rewarded_ad_at=(
                    datetime.now(timezone.utc) - timedelta(minutes=5)
                ),
                penalty_duel_rewarded_ad_provider_index=3,
            )
            db.add(wallet)
            db.commit()
            pending, _ = adsgram_reward.create_onclicka_penalty_duel_reward_session(
                db, 707,
            )

        rejected = client.get(
            "/penalty-duel/rewards/onclicka/callback/wrong-token",
            params={"USERID": 707},
        )
        assert rejected.status_code == 401

        path = f"/penalty-duel/rewards/onclicka/callback/{ONCLICKA_TOKEN}"
        rewarded = client.get(path, params={"USERID": 707})
        assert rewarded.status_code == 200
        assert rewarded.json() == {"status": "ok", "rewarded": True}

        duplicate = client.get(path, params={"USERID": 707})
        assert duplicate.status_code == 200
        assert duplicate.json() == {
            "status": "ok",
            "rewarded": False,
            "reason": "no_pending_session",
        }
        with sessions() as db:
            settled = db.get(AdsgramRewardSession, pending.id)
            assert settled.status == adsgram_reward.CLAIMED
            wallet = db.get(GameTicketWallet, 707)
            assert wallet.game_tickets == 2
            assert wallet.penalty_duel_rewarded_ad_provider_index == 0
            assert db.query(GameTicketLedger).filter_by(
                idempotency_key=f"penalty-duel:ad:onclicka:session:{pending.id}",
            ).count() == 1
    finally:
        engine.dispose()


def test_onclicka_callback_without_pending_session_never_rewards(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        response = client.get(
            f"/penalty-duel/rewards/onclicka/callback/{ONCLICKA_TOKEN}",
            params={"USERID": 707},
        )
        assert response.status_code == 200
        assert response.json()["rewarded"] is False
        with sessions() as db:
            assert db.get(GameTicketWallet, 707) is None
            assert db.query(GameTicketLedger).count() == 0
    finally:
        engine.dispose()


def test_tads_webhook_is_verified_idempotent_and_advances_to_telega(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        path = "/penalty-duel/rewards/tads/webhook?secret=tads-secret"
        payload = {"telegram_id": "707", "widget_id": "11416"}
        rewarded = client.post(path, json=payload)
        duplicate = client.post(path, json=payload)

        assert rewarded.status_code == 200
        assert rewarded.json()["rewarded"] is True
        assert (
            rewarded.json()["wallet"]["next_penalty_duel_rewarded_ad_provider"]
            == "TELEGA"
        )
        assert duplicate.status_code == 200
        with sessions() as db:
            assert db.get(GameTicketWallet, 707).game_tickets == 1
            assert db.query(GameTicketLedger).filter_by(
                operation="PENALTY_AD_GRANT",
            ).count() == 1
    finally:
        engine.dispose()
