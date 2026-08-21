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
from app.routers.wall_rush import router
from app.services import adsgram_reward


def build(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__, WallRushMatch.__table__,
        GameTicketWallet.__table__, GameTicketLedger.__table__,
        AdsgramRewardSession.__table__,
    ])
    sessions = sessionmaker(bind=engine)
    db = sessions()
    db.add(User(telegram_id=101, first_name="TADS User"))
    db.commit()
    db.close()

    monkeypatch.setattr(config, "TADS_WEBHOOK_SECRET", "test-tads-secret")
    monkeypatch.setattr(config, "TADS_WALL_RUSH_WIDGET_ID", "11416")
    app = FastAPI()
    app.include_router(router)

    def dependency():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = dependency
    return TestClient(app), sessions, engine


def test_tads_webhook_rejects_missing_secret(monkeypatch):
    client, _, engine = build(monkeypatch)
    try:
        response = client.post(
            "/wall-rush/rewards/tads/webhook",
            json={"telegram_id": "101", "widget_id": "11416"},
        )
        assert response.status_code == 401
    finally:
        engine.dispose()


def test_tads_webhook_rejects_another_widget(monkeypatch):
    client, _, engine = build(monkeypatch)
    try:
        response = client.post(
            "/wall-rush/rewards/tads/webhook?secret=test-tads-secret",
            json={"telegram_id": "101", "widget_id": "99999"},
        )
        assert response.status_code == 403
    finally:
        engine.dispose()


def test_verified_tads_view_grants_only_one_ticket_per_30_minutes(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        url = "/wall-rush/rewards/tads/webhook?secret=test-tads-secret"
        payload = {"telegram_id": "101", "widget_id": "11416"}
        first = client.post(url, json=payload)
        duplicate = client.post(url, json=payload)

        assert first.status_code == 200
        assert first.json()["status"] == "ok"
        assert duplicate.status_code == 200
        db = sessions()
        assert db.get(GameTicketWallet, 101).game_tickets == 1
        assert db.query(GameTicketLedger).filter_by(operation="AD_GRANT").count() == 1
        db.close()
    finally:
        engine.dispose()


def test_legacy_tads_webhook_settles_pending_penalty_session_exactly_once(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        with sessions() as db:
            pending, _ = adsgram_reward.create_tads_penalty_duel_reward_session(
                db, 101,
            )

        url = "/wall-rush/rewards/tads/webhook?secret=test-tads-secret"
        payload = {"telegram_id": "101", "widget_id": "11416"}
        rewarded = client.post(url, json=payload)
        duplicate = client.post(url, json=payload)

        assert rewarded.status_code == 200
        assert rewarded.json()["rewarded"] is True
        assert duplicate.status_code == 200
        assert duplicate.json() == {
            "status": "ok", "rewarded": False, "reason": "duplicate",
        }
        with sessions() as db:
            assert db.get(AdsgramRewardSession, pending.id).status == adsgram_reward.CLAIMED
            assert db.get(GameTicketWallet, 101).game_tickets == 1
            assert db.query(GameTicketLedger).filter_by(
                operation="PENALTY_AD_GRANT",
            ).count() == 1
            assert db.query(GameTicketLedger).filter_by(operation="AD_GRANT").count() == 0
    finally:
        engine.dispose()
