import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import admin_auth, telegram_auth
from app.core.database import Base, get_db
from app.models.user import User
from app.routers.admin_metrics import router


def init_data(telegram_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Admin"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def headers(telegram_id: int) -> dict[str, str]:
    return {"X-Telegram-Init-Data": init_data(telegram_id)}


def build(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[User.__table__])
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
    return TestClient(app), sessions, engine


def test_user_metrics_are_admin_only_and_count_trailing_30_days(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        now = datetime.now(timezone.utc)
        db = sessions()
        db.add_all([
            User(telegram_id=1, first_name="Active", last_seen_at=now - timedelta(days=2)),
            User(telegram_id=2, first_name="Boundary", last_seen_at=now - timedelta(days=29)),
            User(telegram_id=3, first_name="Inactive", last_seen_at=now - timedelta(days=31)),
            User(telegram_id=4, first_name="Never", last_seen_at=None),
        ])
        db.commit()
        db.close()

        assert client.get("/admin/metrics/users").status_code == 401
        assert client.get("/admin/metrics/users", headers=headers(7001)).status_code == 403

        response = client.get("/admin/metrics/users", headers=headers(9001))
        assert response.status_code == 200
        assert response.json()["total_users"] == 4
        assert response.json()["monthly_active_users"] == 2
        assert response.json()["active_window_days"] == 30
        assert response.json()["generated_at"]
    finally:
        engine.dispose()


def test_user_metrics_return_zero_for_empty_database(monkeypatch):
    client, _sessions, engine = build(monkeypatch)
    try:
        response = client.get("/admin/metrics/users", headers=headers(9001))
        assert response.status_code == 200
        assert response.json()["total_users"] == 0
        assert response.json()["monthly_active_users"] == 0
    finally:
        engine.dispose()


def test_admin_user_list_supports_search_filter_and_pagination(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        now = datetime.now(timezone.utc)
        db = sessions()
        db.add_all([
            User(telegram_id=101, username="alpha", first_name="Ali", last_name="One", last_seen_at=now),
            User(telegram_id=102, username="beta", first_name="Vali", last_name="Two", last_seen_at=now - timedelta(days=40)),
            User(telegram_id=103, username=None, first_name="No Username", last_seen_at=None),
        ])
        db.commit()
        db.close()

        assert client.get("/admin/metrics/users/list").status_code == 401
        assert client.get("/admin/metrics/users/list", headers=headers(7001)).status_code == 403

        response = client.get("/admin/metrics/users/list?per_page=2&page=1", headers=headers(9001))
        assert response.status_code == 200
        assert response.json()["total"] == 3
        assert response.json()["pages"] == 2
        assert len(response.json()["items"]) == 2

        active = client.get("/admin/metrics/users/list?status=ACTIVE", headers=headers(9001)).json()
        assert active["total"] == 1
        assert active["items"][0]["username"] == "alpha"
        assert active["items"][0]["is_active"] is True

        inactive = client.get("/admin/metrics/users/list?status=INACTIVE", headers=headers(9001)).json()
        assert inactive["total"] == 2
        assert all(item["is_active"] is False for item in inactive["items"])

        username = client.get("/admin/metrics/users/list?q=beta", headers=headers(9001)).json()
        assert [item["telegram_id"] for item in username["items"]] == [102]
        telegram_id = client.get("/admin/metrics/users/list?q=103", headers=headers(9001)).json()
        assert telegram_id["items"][0]["username"] is None
        assert set(telegram_id["items"][0]) == {
            "telegram_id", "username", "first_name", "last_name", "language",
            "created_at", "last_seen_at", "is_active",
        }
    finally:
        engine.dispose()


def test_admin_user_list_validates_public_query_limits(monkeypatch):
    client, _sessions, engine = build(monkeypatch)
    try:
        assert client.get("/admin/metrics/users/list?status=UNKNOWN", headers=headers(9001)).status_code == 422
        assert client.get("/admin/metrics/users/list?per_page=51", headers=headers(9001)).status_code == 422
    finally:
        engine.dispose()
