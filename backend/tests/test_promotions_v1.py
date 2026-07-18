import hashlib
import hmac
import json
import importlib.util
from pathlib import Path
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core import admin_auth, telegram_auth
from app.core.database import Base, get_db
from app.models.promotion import Promotion
from app.routers.promotion import admin_router, public_router


def build_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Promotion.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(admin_auth, "ADMIN_TELEGRAM_IDS", frozenset({9001, 9002}))
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)

    def dependency():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = dependency
    return TestClient(app), sessions


def init_data(telegram_id=1001):
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "CMS User"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def admin_headers(actor=9001):
    return {
        "X-Telegram-Init-Data": init_data(actor),
    }


def payload(title="Promotion", priority=0, **extra):
    result = {
        "title": title,
        "button_action": "COIN_SHOP",
        "priority": priority,
    }
    result.update(extra)
    return result


def test_admin_crud_requires_verified_admin_and_tracks_actor(monkeypatch):
    client, _ = build_client(monkeypatch)
    assert client.post("/admin/promotions", json=payload()).status_code == 401
    assert client.post(
        "/admin/promotions",
        json=payload(),
        headers={"X-Telegram-Init-Data": init_data(7777)},
    ).status_code == 403
    assert client.post(
        "/admin/promotions",
        json=payload(),
        headers={"X-Internal-Api-Key": "test-internal-key"},
    ).status_code == 401
    created = client.post(
        "/admin/promotions", json=payload(), headers=admin_headers()
    )
    assert created.status_code == 201
    promotion = created.json()
    assert promotion["status"] == "DRAFT"
    assert promotion["created_by"] == 9001

    promotion_id = promotion["id"]
    updated = client.patch(
        f"/admin/promotions/{promotion_id}",
        json={"title": "Updated", "priority": 25},
        headers=admin_headers(9002),
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated"
    assert updated.json()["updated_by"] == 9002
    assert client.get(
        f"/admin/promotions/{promotion_id}", headers=admin_headers()
    ).json()["priority"] == 25


def test_invalid_init_data_is_unauthorized(monkeypatch):
    client, _ = build_client(monkeypatch)
    response = client.get(
        "/admin/promotions",
        headers={"X-Telegram-Init-Data": "invalid"},
    )
    assert response.status_code == 401


def test_spoofed_actor_headers_are_ignored(monkeypatch):
    client, _ = build_client(monkeypatch)
    headers = admin_headers(9001)
    headers["X-Admin-Telegram-Id"] = "7777"
    created = client.post(
        "/admin/promotions", json=payload(), headers=headers
    )
    assert created.status_code == 201
    assert created.json()["created_by"] == 9001


def test_priority_and_authenticated_public_active_endpoint(monkeypatch):
    client, _ = build_client(monkeypatch)
    for title, priority in (("Low", 1), ("High", 100), ("Middle", 20)):
        response = client.post(
            "/admin/promotions",
            json=payload(title, priority, status="ACTIVE"),
            headers=admin_headers(),
        )
        assert response.status_code == 201

    assert client.get("/promotions/active").status_code == 401
    response = client.get(
        "/promotions/active",
        headers={"X-Telegram-Init-Data": init_data()},
    )
    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["High", "Middle", "Low"]
    assert "status" not in response.json()[0]
    assert "created_by" not in response.json()[0]


def test_scheduled_promotion_auto_activates(monkeypatch):
    client, sessions = build_client(monkeypatch)
    db = sessions()
    promotion = Promotion(
        title="Scheduled",
        button_action="NONE",
        priority=3,
        status="SCHEDULED",
        start_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.add(promotion)
    db.commit()
    promotion_id = promotion.id
    db.close()

    response = client.get(
        "/promotions/active",
        headers={"X-Telegram-Init-Data": init_data()},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [promotion_id]
    detail = client.get(
        f"/admin/promotions/{promotion_id}", headers=admin_headers()
    )
    assert detail.json()["status"] == "ACTIVE"


def test_active_promotion_auto_expires(monkeypatch):
    client, sessions = build_client(monkeypatch)
    db = sessions()
    promotion = Promotion(
        title="Expired",
        button_action="NONE",
        priority=3,
        status="ACTIVE",
        end_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db.add(promotion)
    db.commit()
    promotion_id = promotion.id
    db.close()

    response = client.get(
        "/promotions/active",
        headers={"X-Telegram-Init-Data": init_data()},
    )
    assert response.json() == []
    assert client.get(
        f"/admin/promotions/{promotion_id}", headers=admin_headers()
    ).json()["status"] == "EXPIRED"


def test_soft_delete_restore_and_lifecycle_actions(monkeypatch):
    client, _ = build_client(monkeypatch)
    created = client.post(
        "/admin/promotions",
        json=payload(status="ACTIVE"),
        headers=admin_headers(),
    ).json()
    promotion_id = created["id"]
    paused = client.post(
        f"/admin/promotions/{promotion_id}/pause", headers=admin_headers()
    )
    assert paused.json()["status"] == "PAUSED"
    activated = client.post(
        f"/admin/promotions/{promotion_id}/activate", headers=admin_headers()
    )
    assert activated.json()["status"] == "ACTIVE"
    deactivated = client.post(
        f"/admin/promotions/{promotion_id}/deactivate", headers=admin_headers()
    )
    assert deactivated.json()["status"] == "DRAFT"

    deleted = client.delete(
        f"/admin/promotions/{promotion_id}", headers=admin_headers()
    )
    assert deleted.json()["status"] == "DELETED"
    assert deleted.json()["deleted_at"] is not None
    assert client.get(
        f"/admin/promotions/{promotion_id}", headers=admin_headers()
    ).status_code == 404
    restored = client.post(
        f"/admin/promotions/{promotion_id}/restore", headers=admin_headers()
    )
    assert restored.json()["status"] == "DRAFT"
    assert restored.json()["deleted_at"] is None


def test_limits_and_action_contract(monkeypatch):
    client, sessions = build_client(monkeypatch)
    invalid = client.post(
        "/admin/promotions",
        json=payload(button_action="URL"),
        headers=admin_headers(),
    )
    assert invalid.status_code == 422

    db = sessions()
    db.add(
        Promotion(
            title="Limit reached",
            button_action="NONE",
            priority=100,
            status="ACTIVE",
            max_views=5,
            view_count=5,
        )
    )
    db.commit()
    db.close()
    response = client.get(
        "/promotions/active",
        headers={"X-Telegram-Init-Data": init_data()},
    )
    assert response.json() == []


def test_promotions_migration_upgrade_and_downgrade(monkeypatch):
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260719_promotions_v1.py"
    )
    spec = importlib.util.spec_from_file_location("promotions_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()
        assert "promotions" in __import__("sqlalchemy").inspect(connection).get_table_names()
        columns = {
            column["name"]
            for column in __import__("sqlalchemy").inspect(connection).get_columns("promotions")
        }
        assert {"title", "button_action", "priority", "deleted_at"} <= columns
        migration.downgrade()
        assert "promotions" not in __import__("sqlalchemy").inspect(connection).get_table_names()
