import hashlib
import hmac
import importlib.util
import json
import time
from pathlib import Path
from urllib.parse import urlencode

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import telegram_auth
from app.core.database import Base, get_db
from app.models.campaign import Campaign, CampaignRecipient
from app.models.promotion import Promotion
from app.models.user import User
from app.routers.notification import router


def init_data(telegram_id=1001):
    values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": telegram_id, "first_name": "User"}, separators=(",", ":"))}
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def headers(telegram_id=1001):
    return {"X-Telegram-Init-Data": init_data(telegram_id)}


def build_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, Promotion.__table__, Campaign.__table__, CampaignRecipient.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
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


def seed(sessions):
    db = sessions()
    db.add_all([User(telegram_id=1001, first_name="Owner", is_banned=False), User(telegram_id=1002, first_name="Other", is_banned=False)])
    campaign = Campaign(title="Premium Campaign", message="New LEVEL_GROUP offer", image_url="https://cdn.example/banner.webp", badge="YANGI", button_action="COIN_SHOP", promotion_id=None, audience_type="ALL_USERS", schedule_type="NOW", status="COMPLETED", created_by=9001, updated_by=9001)
    second_campaign = Campaign(title="Arena Campaign", message="Arena is ready", badge="LIVE", button_action="ARENA", audience_type="ALL_USERS", schedule_type="NOW", status="RUNNING", created_by=9001, updated_by=9001)
    db.add_all([campaign, second_campaign])
    db.flush()
    recipients = [
        CampaignRecipient(campaign_id=campaign.id, user_id=1001, status="PENDING"),
        CampaignRecipient(campaign_id=second_campaign.id, user_id=1001, status="SENT"),
        CampaignRecipient(campaign_id=campaign.id, user_id=1002, status="PENDING"),
    ]
    db.add_all(recipients)
    db.commit()
    result = campaign.id, [recipient.id for recipient in recipients]
    db.close()
    return result


def test_list_unread_count_and_verified_auth(monkeypatch):
    client, sessions = build_client(monkeypatch)
    _, recipient_ids = seed(sessions)
    assert client.get("/notifications").status_code == 401
    assert client.get("/notifications", headers={"X-Telegram-Init-Data": "invalid"}).status_code == 401
    response = client.get("/notifications", headers=headers())
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == set(recipient_ids[:2])
    item = next(value for value in response.json() if value["title"] == "Premium Campaign")
    assert item["title"] == "Premium Campaign" and item["badge"] == "YANGI"
    assert item["status"] == "UNREAD" and item["read_at"] is None
    assert client.get("/notifications/unread-count", headers=headers()).json() == {"unread_count": 2}


def test_foreign_notification_is_forbidden(monkeypatch):
    client, sessions = build_client(monkeypatch)
    _, recipient_ids = seed(sessions)
    foreign_id = recipient_ids[2]
    for method, path in (("post", f"/notifications/{foreign_id}/read"), ("post", f"/notifications/{foreign_id}/click"), ("delete", f"/notifications/{foreign_id}")):
        assert getattr(client, method)(path, headers=headers()).status_code == 403


def test_read_is_idempotent(monkeypatch):
    client, sessions = build_client(monkeypatch)
    _, recipient_ids = seed(sessions)
    notification_id = recipient_ids[0]
    first = client.post(f"/notifications/{notification_id}/read", headers=headers()).json()
    second = client.post(f"/notifications/{notification_id}/read", headers=headers()).json()
    assert first["status"] == second["status"] == "READ"
    assert first["read_at"] == second["read_at"]
    assert client.get("/notifications/unread-count", headers=headers()).json()["unread_count"] == 1


def test_read_all_is_scoped_and_idempotent(monkeypatch):
    client, sessions = build_client(monkeypatch)
    _, recipient_ids = seed(sessions)
    assert client.post("/notifications/read-all", headers=headers()).json() == {"updated_count": 2, "unread_count": 0}
    assert client.post("/notifications/read-all", headers=headers()).json() == {"updated_count": 0, "unread_count": 0}
    assert client.get("/notifications/unread-count", headers=headers(1002)).json()["unread_count"] == 1
    db = sessions()
    assert db.get(CampaignRecipient, recipient_ids[2]).status == "PENDING"
    db.close()


def test_click_atomically_updates_recipient_and_campaign_statistics(monkeypatch):
    client, sessions = build_client(monkeypatch)
    campaign_id, recipient_ids = seed(sessions)
    clicked = client.post(f"/notifications/{recipient_ids[0]}/click", headers=headers()).json()
    assert clicked["status"] == "CLICKED"
    assert clicked["clicked_at"] and clicked["read_at"]
    repeated = client.post(f"/notifications/{recipient_ids[0]}/click", headers=headers()).json()
    assert repeated["clicked_at"] == clicked["clicked_at"]
    db = sessions()
    campaign = db.get(Campaign, campaign_id)
    assert (campaign.sent_count, campaign.opened_count, campaign.clicked_count) == (1, 1, 1)
    db.close()


def test_delete_is_idempotent_soft_dismiss(monkeypatch):
    client, sessions = build_client(monkeypatch)
    _, recipient_ids = seed(sessions)
    notification_id = recipient_ids[0]
    first = client.delete(f"/notifications/{notification_id}", headers=headers()).json()
    second = client.delete(f"/notifications/{notification_id}", headers=headers()).json()
    assert first["status"] == second["status"] == "DISMISSED"
    assert first["dismissed_at"] == second["dismissed_at"]
    assert notification_id not in {item["id"] for item in client.get("/notifications", headers=headers()).json()}
    db = sessions()
    assert db.get(CampaignRecipient, notification_id) is not None
    db.close()


def test_user_notification_migration(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260719_user_notifications.py"
    spec = importlib.util.spec_from_file_location("user_notification_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE campaigns (id INTEGER PRIMARY KEY, title VARCHAR(160), message TEXT)"))
        connection.execute(text("CREATE TABLE campaign_recipients (id INTEGER PRIMARY KEY, campaign_id INTEGER, user_id BIGINT, status VARCHAR(20), opened_at DATETIME, clicked_at DATETIME, created_at DATETIME)"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        recipient_columns = {column["name"] for column in __import__("sqlalchemy").inspect(connection).get_columns("campaign_recipients")}
        assert {"read_at", "dismissed_at"} <= recipient_columns
        migration.downgrade()
