import hashlib
import hmac
import importlib.util
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import admin_auth, telegram_auth
from app.core.database import Base, get_db
from app.models.campaign import Campaign, CampaignRecipient
from app.models.match import Match, MatchGameType, MatchStatus
from app.models.order import Order
from app.models.promotion import Promotion
from app.models.referral import Referral
from app.models.user import User
from app.models.wallet import Wallet
from app.models.wheel import WheelSpin
from app.routers.campaign import router


TABLES = [User.__table__, Promotion.__table__, Wallet.__table__, Order.__table__, Match.__table__, WheelSpin.__table__, Referral.__table__, Campaign.__table__, CampaignRecipient.__table__]


def init_data(telegram_id=9001):
    values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": telegram_id, "first_name": "Admin"}, separators=(",", ":"))}
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def headers(actor=9001):
    return {"X-Telegram-Init-Data": init_data(actor)}


def build_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(admin_auth, "ADMIN_TELEGRAM_IDS", frozenset({9001}))
    app = FastAPI()
    app.include_router(router)

    def dependency():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = dependency
    return TestClient(app), sessions


def seed_audiences(sessions):
    now = datetime.now(timezone.utc)
    db = sessions()
    db.add_all(User(telegram_id=user_id, first_name=f"User {user_id}", is_banned=user_id == 9, last_seen_at=now - (timedelta(days=60) if user_id == 7 else timedelta(hours=1))) for user_id in range(1, 10))
    db.flush()
    db.add_all([Wallet(telegram_id=8, uzs_balance=2_000_000, efc_balance=100), Wallet(telegram_id=1, uzs_balance=10, efc_balance=10)])
    db.add(Referral(referrer_telegram_id=1, referred_telegram_id=2, status="ACTIVE"))
    db.add(Order(telegram_id=3, product_id=1, product_title="Coin", coins_amount=130, price_uzs=10000, status="COMPLETED"))
    db.add(Match(creator_telegram_id=4, opponent_telegram_id=5, efc_amount=100, total_pool=200, commission_amount=10, winner_reward=190, status=MatchStatus.COMPLETED, game_type=MatchGameType.EFOOTBALL, scheduled_at=now))
    db.add(WheelSpin(telegram_id=6, spin_type="FREE", reward_code="NONE", reward_type="NONE", reward_amount=0, global_spin_number=1, status="COMPLETED"))
    db.commit()
    db.close()


def create_campaign(client, audience):
    response = client.post("/admin/campaigns", json={"title": audience, "message": "Message", "audience_type": audience, "schedule_type": "NOW"}, headers=headers())
    assert response.status_code == 201
    campaign_id = response.json()["id"]
    assert client.post(f"/admin/campaigns/{campaign_id}/schedule", headers=headers()).status_code == 200
    return campaign_id


@pytest.mark.parametrize(("audience", "options", "expected"), [
    ("ALL_USERS", {}, set(range(1, 9))),
    ("REFERRAL_USERS", {}, {2}),
    ("COIN_SHOP_USERS", {}, {3}),
    ("ARENA_USERS", {}, {4, 5}),
    ("WHEEL_USERS", {}, {6}),
    ("INACTIVE_USERS", {"inactive_days": 30}, {7}),
    ("VIP_USERS", {"vip_min_uzs": 1_000_000}, {8}),
    ("CUSTOM", {"custom_user_ids": [1, 9, 999]}, {1}),
])
def test_each_audience_selector(monkeypatch, audience, options, expected):
    client, sessions = build_client(monkeypatch)
    seed_audiences(sessions)
    campaign_id = create_campaign(client, audience)
    prepared = client.post(f"/admin/campaigns/{campaign_id}/prepare", json=options, headers=headers())
    assert prepared.status_code == 200
    assert prepared.json()["campaign"]["status"] == "READY"
    recipients = client.get(f"/admin/campaigns/{campaign_id}/recipients", headers=headers()).json()
    assert {item["user_id"] for item in recipients} == expected
    assert all(item["status"] == "PENDING" for item in recipients)


def test_snapshot_is_immutable_and_pipeline_completes(monkeypatch):
    client, sessions = build_client(monkeypatch)
    seed_audiences(sessions)
    campaign_id = create_campaign(client, "ALL_USERS")
    assert client.post(f"/admin/campaigns/{campaign_id}/prepare", json={}, headers=headers()).json()["recipient_count"] == 8
    db = sessions()
    db.add(User(telegram_id=10, first_name="New User", is_banned=False, last_seen_at=datetime.now(timezone.utc)))
    db.commit()
    db.close()
    assert len(client.get(f"/admin/campaigns/{campaign_id}/recipients", headers=headers()).json()) == 8
    assert client.post(f"/admin/campaigns/{campaign_id}/prepare", json={}, headers=headers()).status_code == 409
    assert client.post(f"/admin/campaigns/{campaign_id}/start", headers=headers()).json()["status"] == "RUNNING"
    assert client.post(f"/admin/campaigns/{campaign_id}/complete", headers=headers()).json()["status"] == "COMPLETED"


def test_statistics_recalculate_from_recipient_statuses(monkeypatch):
    client, sessions = build_client(monkeypatch)
    seed_audiences(sessions)
    campaign_id = create_campaign(client, "CUSTOM")
    client.post(f"/admin/campaigns/{campaign_id}/prepare", json={"custom_user_ids": [1, 2, 3, 4, 5]}, headers=headers())
    db = sessions()
    recipients = db.query(CampaignRecipient).filter_by(campaign_id=campaign_id).order_by(CampaignRecipient.id).all()
    for recipient, status in zip(recipients, ["SENT", "OPENED", "CLICKED", "FAILED", "SKIPPED"]):
        recipient.status = status
    db.commit()
    db.close()
    detail = client.get(f"/admin/campaigns/{campaign_id}", headers=headers()).json()
    assert (detail["sent_count"], detail["opened_count"], detail["clicked_count"], detail["failed_count"]) == (3, 2, 1, 1)
    assert detail["ctr"] == 33.33 and detail["failure_rate"] == 33.33


def test_execution_requires_verified_admin_and_selector_options(monkeypatch):
    client, sessions = build_client(monkeypatch)
    seed_audiences(sessions)
    campaign_id = create_campaign(client, "VIP_USERS")
    assert client.post(f"/admin/campaigns/{campaign_id}/prepare", json={}).status_code == 401
    assert client.post(f"/admin/campaigns/{campaign_id}/prepare", json={}, headers=headers(7777)).status_code == 403
    assert client.post(f"/admin/campaigns/{campaign_id}/prepare", json={}, headers=headers()).status_code == 422


def test_execution_migration_upgrade_and_downgrade(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260719_campaign_execution.py"
    spec = importlib.util.spec_from_file_location("campaign_execution_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for table in (User.__table__, Promotion.__table__, Campaign.__table__):
            table.create(connection)
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()
        assert "campaign_recipients" in __import__("sqlalchemy").inspect(connection).get_table_names()
        migration.downgrade()
        assert "campaign_recipients" not in __import__("sqlalchemy").inspect(connection).get_table_names()
