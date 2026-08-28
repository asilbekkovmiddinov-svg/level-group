import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all foreign-key targets
from app.core import admin_auth
from app.core.admin_auth import require_promotions_admin
from app.core.database import Base, get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.models.shop import ShopPurchase, ShopSettings
from app.models.user import User
from app.models.wallet import Wallet
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.routers.miniapp_shop import admin_router, router
from app.services import shop


@pytest.fixture()
def miniapp_shop_app(monkeypatch):
    monkeypatch.setattr(shop.config, "SHOP_MAX_EFC_PER_PURCHASE", 10_000)
    monkeypatch.setattr(shop.config, "SHOP_MAX_TICKETS_PER_PURCHASE", 100)
    monkeypatch.setattr(admin_auth, "ADMIN_TELEGRAM_IDS", {99})
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as seed:
        seed.add_all([
            User(telegram_id=42, first_name="Player"),
            User(telegram_id=99, first_name="Admin"),
            Wallet(
                telegram_id=42,
                uzs_balance=100_000,
                efc_balance=20,
                locked_uzs=0,
                locked_efc=0,
                locked_reward_efc=0,
            ),
            GameTicketWallet(telegram_id=42, tournament_tickets=1),
            ShopSettings(
                id="default",
                efc_price_uzs=1_000,
                ticket_price_efc=10,
            ),
        ])
        seed.commit()

    identity = {"telegram_id": 42}

    def override_db():
        with sessions() as db:
            yield db

    def override_user():
        return TelegramUser(identity["telegram_id"], "Test", None, "uz")

    application = FastAPI()
    application.include_router(router)
    application.include_router(admin_router)
    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_current_telegram_user] = override_user

    with TestClient(application) as client:
        yield client, sessions, identity


def test_catalog_uses_verified_user_identity(miniapp_shop_app):
    client, _sessions, _identity = miniapp_shop_app
    response = client.get("/wallet-shop/catalog")
    assert response.status_code == 200
    assert response.json() == {
        "efc_price_uzs": 1000.0,
        "ticket_price_efc": 10.0,
        "max_efc_per_purchase": 10000,
        "max_tickets_per_purchase": 100,
        "efc_balance": 20.0,
        "uzs_balance": 100000.0,
        "ticket_balance": 1,
    }


def test_user_cannot_select_another_telegram_id(miniapp_shop_app):
    client, sessions, _identity = miniapp_shop_app
    response = client.post(
        "/wallet-shop/buy-ticket",
        headers={"Idempotency-Key": "forged-user"},
        json={"quantity": 1, "telegram_id": 99},
    )
    assert response.status_code == 422
    with sessions() as db:
        assert db.get(Wallet, 42).efc_balance == 20
        assert db.get(GameTicketWallet, 42).tournament_tickets == 1


def test_ticket_purchase_is_exactly_once_through_miniapp(miniapp_shop_app):
    client, sessions, _identity = miniapp_shop_app
    headers = {"Idempotency-Key": "miniapp-ticket-once"}
    first = client.post(
        "/wallet-shop/buy-ticket", headers=headers, json={"quantity": 2}
    )
    replay = client.post(
        "/wallet-shop/buy-ticket", headers=headers, json={"quantity": 2}
    )
    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["purchase_id"] == replay.json()["purchase_id"]
    with sessions() as db:
        assert db.get(Wallet, 42).efc_balance == 0
        assert db.get(GameTicketWallet, 42).tournament_tickets == 3
        assert db.query(ShopPurchase).count() == 1
        assert db.query(GameTicketLedger).count() == 1


def test_missing_idempotency_key_never_spends_balance(miniapp_shop_app):
    client, sessions, _identity = miniapp_shop_app
    response = client.post("/wallet-shop/buy-efc", json={"efc_amount": 10})
    assert response.status_code == 422
    with sessions() as db:
        assert db.get(Wallet, 42).uzs_balance == 100_000
        assert db.get(Wallet, 42).efc_balance == 20


def test_only_admin_can_update_prices(miniapp_shop_app):
    client, sessions, identity = miniapp_shop_app
    denied = client.put(
        "/admin/wallet-shop/settings",
        json={"efc_price_uzs": 750, "ticket_price_efc": 7.5},
    )
    assert denied.status_code == 403

    identity["telegram_id"] = 99
    updated = client.put(
        "/admin/wallet-shop/settings",
        json={"efc_price_uzs": 750, "ticket_price_efc": 7.5},
    )
    assert updated.status_code == 200
    assert updated.json()["efc_price_uzs"] == 750
    assert updated.json()["ticket_price_efc"] == 7.5
    assert updated.json()["updated_by"] == 99
    with sessions() as db:
        settings = db.get(ShopSettings, "default")
        assert settings.updated_by == 99


def test_router_auth_dependencies_are_explicit():
    for route in router.routes:
        dependencies = {item.call for item in route.dependant.dependencies}
        assert get_current_telegram_user in dependencies
    for route in admin_router.routes:
        dependencies = {item.call for item in route.dependant.dependencies}
        assert require_promotions_admin in dependencies
