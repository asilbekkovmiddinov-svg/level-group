import hashlib
import hmac
import json
import time
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import admin_auth, telegram_auth
from app.core.database import Base, get_db
from app.models.user import User
from app.routers.admin_user_stats import router
from app.services.arena_time import utc_now


def init_data(telegram_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Admin"}, separators=(",", ":")
        ),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def build_client(monkeypatch):
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
    return TestClient(app), sessions


def test_user_stats_are_admin_only_and_count_online_users(monkeypatch):
    client, sessions = build_client(monkeypatch)
    now = utc_now()
    with sessions() as db:
        db.add_all(
            [
                User(telegram_id=1, first_name="Online", last_seen_at=now),
                User(
                    telegram_id=2,
                    first_name="Offline",
                    last_seen_at=now - timedelta(minutes=10),
                ),
                User(
                    telegram_id=3,
                    first_name="Banned",
                    is_banned=True,
                    last_seen_at=now,
                ),
            ]
        )
        db.commit()

    assert client.get("/admin/users/stats").status_code == 401
    assert client.get(
        "/admin/users/stats",
        headers={"X-Telegram-Init-Data": init_data(7777)},
    ).status_code == 403

    response = client.get(
        "/admin/users/stats",
        headers={"X-Telegram-Init-Data": init_data(9001)},
    )
    assert response.status_code == 200
    assert response.json() == {"total_users": 3, "online_users": 1}
