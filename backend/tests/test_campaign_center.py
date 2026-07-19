import hashlib
import hmac
import importlib.util
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import admin_auth, telegram_auth
from app.core.database import Base, get_db
from app.models.campaign import Campaign
from app.models.promotion import Promotion
from app.routers.campaign import router


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
    Base.metadata.create_all(engine, tables=[Promotion.__table__, Campaign.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(admin_auth, "ADMIN_TELEGRAM_IDS", frozenset({9001, 9002}))
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


def payload(**extra):
    result = {"title": "Summer Campaign", "message": "Premium promotion is live", "audience_type": "ALL_USERS", "schedule_type": "NOW", "button_action": "COIN_SHOP"}
    result.update(extra)
    return result


def test_campaign_crud_and_verified_actor(monkeypatch):
    client, _ = build_client(monkeypatch)
    assert client.post("/admin/campaigns", json=payload()).status_code == 401
    assert client.post("/admin/campaigns", json=payload(), headers=headers(7777)).status_code == 403
    assert client.post("/admin/campaigns", json=payload(), headers={"X-Telegram-Init-Data": "invalid"}).status_code == 401
    created = client.post("/admin/campaigns", json=payload(), headers=headers()).json()
    assert created["status"] == "DRAFT"
    assert created["created_by"] == created["updated_by"] == 9001
    campaign_id = created["id"]
    updated = client.patch(f"/admin/campaigns/{campaign_id}", json={"title": "Updated"}, headers=headers(9002))
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated"
    assert updated.json()["updated_by"] == 9002
    assert len(client.get("/admin/campaigns", headers=headers()).json()) == 1
    assert client.get(f"/admin/campaigns/{campaign_id}", headers=headers()).json()["id"] == campaign_id


def test_schedule_and_button_validation(monkeypatch):
    client, _ = build_client(monkeypatch)
    missing_time = client.post("/admin/campaigns", json=payload(schedule_type="SCHEDULED"), headers=headers())
    assert missing_time.status_code == 422
    missing_target = client.post("/admin/campaigns", json=payload(button_action="URL"), headers=headers())
    assert missing_target.status_code == 422
    invalid_status = client.post("/admin/campaigns", json=payload(status="RUNNING"), headers=headers())
    assert invalid_status.status_code == 409
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    scheduled = client.post("/admin/campaigns", json=payload(schedule_type="SCHEDULED", scheduled_at=future, status="SCHEDULED"), headers=headers())
    assert scheduled.status_code == 201
    assert scheduled.json()["scheduled_at"] is not None


def test_lifecycle_soft_delete_and_restore(monkeypatch):
    client, _ = build_client(monkeypatch)
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    campaign = client.post("/admin/campaigns", json=payload(schedule_type="SCHEDULED", scheduled_at=future, status="SCHEDULED"), headers=headers()).json()
    campaign_id = campaign["id"]
    assert client.post(f"/admin/campaigns/{campaign_id}/pause", headers=headers()).json()["status"] == "PAUSED"
    assert client.post(f"/admin/campaigns/{campaign_id}/resume", headers=headers()).json()["status"] == "SCHEDULED"
    assert client.post(f"/admin/campaigns/{campaign_id}/cancel", headers=headers()).json()["status"] == "CANCELLED"
    assert client.post(f"/admin/campaigns/{campaign_id}/resume", headers=headers()).status_code == 409
    deleted = client.delete(f"/admin/campaigns/{campaign_id}", headers=headers()).json()
    assert deleted["status"] == "DELETED" and deleted["deleted_at"]
    assert client.get(f"/admin/campaigns/{campaign_id}", headers=headers()).status_code == 404
    restored = client.post(f"/admin/campaigns/{campaign_id}/restore", headers=headers()).json()
    assert restored["status"] == "SCHEDULED" and restored["deleted_at"] is None


def test_statistics_are_calculated_safely(monkeypatch):
    client, sessions = build_client(monkeypatch)
    campaign_id = client.post("/admin/campaigns", json=payload(), headers=headers()).json()["id"]
    db = sessions()
    campaign = db.get(Campaign, campaign_id)
    campaign.sent_count = 200
    campaign.opened_count = 125
    campaign.clicked_count = 25
    campaign.failed_count = 10
    db.commit()
    db.close()
    detail = client.get(f"/admin/campaigns/{campaign_id}", headers=headers()).json()
    assert detail["sent_count"] == 200 and detail["opened_count"] == 125
    assert detail["ctr"] == 12.5
    assert detail["failure_rate"] == 5.0


def test_optional_promotion_must_exist(monkeypatch):
    client, sessions = build_client(monkeypatch)
    assert client.post("/admin/campaigns", json=payload(promotion_id=999), headers=headers()).status_code == 422
    db = sessions()
    promotion = Promotion(title="Linked", button_action="NONE", status="DRAFT", priority=0)
    db.add(promotion)
    db.commit()
    promotion_id = promotion.id
    db.close()
    response = client.post("/admin/campaigns", json=payload(promotion_id=promotion_id), headers=headers())
    assert response.status_code == 201
    assert response.json()["promotion_id"] == promotion_id


def test_campaign_migration_upgrade_and_downgrade(monkeypatch):
    migration_path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260719_campaign_center_v1.py"
    spec = importlib.util.spec_from_file_location("campaign_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        Promotion.__table__.create(connection)
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()
        inspector = __import__("sqlalchemy").inspect(connection)
        assert "campaigns" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("campaigns")}
        assert {"audience_type", "schedule_type", "sent_count", "promotion_id", "deleted_at"} <= columns
        migration.downgrade()
        assert "campaigns" not in __import__("sqlalchemy").inspect(connection).get_table_names()
