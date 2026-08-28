from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all foreign-key targets
from app.core import admin_auth
from app.core.admin_auth import require_promotions_admin
from app.core.database import Base, get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.models.arena_promocode import (
    ArenaTicketPromocode,
    ArenaTicketPromocodeClaim,
)
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.routers.arena_promocode_admin import router as admin_router
from app.routers.arena_v5 import router as arena_router


@pytest.fixture()
def promo_app(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as seed:
        seed.add_all([
            User(telegram_id=101, first_name="Player"),
            User(telegram_id=9001, first_name="Admin"),
        ])
        seed.commit()

    identity = {"telegram_id": 101}
    monkeypatch.setattr(admin_auth, "ADMIN_TELEGRAM_IDS", {9001})

    def override_db():
        with sessions() as db:
            yield db

    def override_user():
        telegram_id = identity["telegram_id"]
        return TelegramUser(telegram_id, "Test", None, "uz")

    application = FastAPI()
    application.include_router(arena_router)
    application.include_router(admin_router)
    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_current_telegram_user] = override_user

    with TestClient(application) as client:
        yield client, sessions, identity


def test_admin_creates_code_and_user_claims_ticket_once(promo_app):
    client, sessions, identity = promo_app
    identity["telegram_id"] = 9001
    created = client.post(
        "/admin/arena-promocodes",
        json={
            "code": " arena 10 ",
            "ticket_amount": 10,
            "usage_limit": 100,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert created.status_code == 201
    assert created.json()["code"] == "ARENA10"

    identity["telegram_id"] = 101
    claimed = client.post("/arena/v5/promocode/claim", json={"code": " arena10 "})
    duplicate = client.post("/arena/v5/promocode/claim", json={"code": "ARENA10"})

    assert claimed.status_code == 200
    assert claimed.json() == {
        "code": "ARENA10",
        "ticket_amount": 10,
        "ticket_balance": 10,
    }
    assert duplicate.status_code == 409
    assert "avval foydalangansiz" in duplicate.json()["detail"]

    with sessions() as db:
        promo = db.execute(select(ArenaTicketPromocode)).scalar_one()
        assert promo.usage_count == 1
        assert db.get(GameTicketWallet, 101).tournament_tickets == 10
        assert db.query(ArenaTicketPromocodeClaim).count() == 1
        ledger = db.query(GameTicketLedger).one()
        assert ledger.operation == "PROMOCODE_REWARD"
        assert ledger.amount == 10


def test_limit_expiry_and_inactive_codes_never_grant_tickets(promo_app):
    client, sessions, identity = promo_app
    with sessions() as db:
        db.add_all([
            ArenaTicketPromocode(
                code="FULL",
                ticket_amount=3,
                usage_limit=1,
                usage_count=1,
                created_by=9001,
            ),
            ArenaTicketPromocode(
                code="OLD",
                ticket_amount=4,
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                created_by=9001,
            ),
            ArenaTicketPromocode(
                code="OFF",
                ticket_amount=5,
                is_active=False,
                created_by=9001,
            ),
        ])
        db.commit()

    identity["telegram_id"] = 101
    assert client.post("/arena/v5/promocode/claim", json={"code": "FULL"}).status_code == 409
    assert client.post("/arena/v5/promocode/claim", json={"code": "OLD"}).status_code == 409
    assert client.post("/arena/v5/promocode/claim", json={"code": "OFF"}).status_code == 404

    with sessions() as db:
        assert db.get(GameTicketWallet, 101) is None
        assert db.query(GameTicketLedger).count() == 0
        assert db.query(ArenaTicketPromocodeClaim).count() == 0


def test_admin_routes_reject_an_ordinary_user(promo_app):
    client, _sessions, identity = promo_app
    identity["telegram_id"] = 101

    assert client.get("/admin/arena-promocodes").status_code == 403
    assert client.post(
        "/admin/arena-promocodes",
        json={"code": "NOPE", "ticket_amount": 1},
    ).status_code == 403


def test_admin_rejects_unsafe_code_characters_and_unbounded_limit(promo_app):
    client, _sessions, identity = promo_app
    identity["telegram_id"] = 9001

    unsafe = client.post(
        "/admin/arena-promocodes",
        json={"code": "<ARENA>", "ticket_amount": 1},
    )
    too_large = client.post(
        "/admin/arena-promocodes",
        json={"code": "ARENA", "ticket_amount": 1, "usage_limit": 1_000_001},
    )

    assert unsafe.status_code == 422
    assert too_large.status_code == 422


def test_admin_can_deactivate_and_reactivate_code_idempotently(promo_app):
    client, _sessions, identity = promo_app
    identity["telegram_id"] = 9001
    created = client.post(
        "/admin/arena-promocodes",
        json={"code": "REALTEST", "ticket_amount": 2},
    ).json()

    first_off = client.post(f"/admin/arena-promocodes/{created['id']}/deactivate")
    second_off = client.post(f"/admin/arena-promocodes/{created['id']}/deactivate")
    activated = client.post(f"/admin/arena-promocodes/{created['id']}/activate")
    listed = client.get("/admin/arena-promocodes")

    assert first_off.status_code == second_off.status_code == activated.status_code == 200
    assert first_off.json()["is_active"] is False
    assert second_off.json()["is_active"] is False
    assert activated.json()["is_active"] is True
    assert listed.status_code == 200
    assert [item["code"] for item in listed.json()] == ["REALTEST"]
