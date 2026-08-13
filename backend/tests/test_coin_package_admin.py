import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import admin_auth, telegram_auth
from app.core.database import Base, get_db
from app.models.coin_promotion import CoinPromotion
from app.models.order import Order
from app.models.product import Product
from app.routers.coin_package_admin import router as package_router
from app.routers.coin_promotion_admin import router as promotion_router
from app.core.seed_products import seed_products


def init_data(telegram_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Admin"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def headers(telegram_id: int = 9001) -> dict[str, str]:
    return {"X-Telegram-Init-Data": init_data(telegram_id)}


def build(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Product.__table__, CoinPromotion.__table__, Order.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(admin_auth, "ADMIN_TELEGRAM_IDS", frozenset({9001}))
    app = FastAPI()
    app.include_router(package_router)
    app.include_router(promotion_router)

    def dependency():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = dependency
    return TestClient(app), sessions, engine


def package(**extra):
    value = {"coin_amount": 840, "price_uzs": 70000, "scope": "ANDROID", "is_active": True}
    value.update(extra)
    return value


def promotion(package_id: int) -> dict:
    now = time.time()
    from datetime import datetime, timezone
    return {
        "coin_package_id": package_id,
        "title": "840 Coin aksiya",
        "original_price": 70000,
        "promotion_price": 60000,
        "total_quantity": 10,
        "per_user_limit": 1,
        "start_at": datetime.fromtimestamp(now - 60, timezone.utc).isoformat(),
        "end_at": datetime.fromtimestamp(now + 3600, timezone.utc).isoformat(),
    }


def test_admin_creates_edits_and_deactivates_database_package(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        assert client.post("/admin/coin-packages", json=package()).status_code == 401
        assert client.post("/admin/coin-packages", json=package(), headers=headers(7001)).status_code == 403

        created = client.post("/admin/coin-packages", json=package(), headers=headers())
        assert created.status_code == 201
        package_id = created.json()["id"]
        db = sessions()
        assert db.get(Product, package_id).coins_amount == 840
        db.close()

        duplicate = client.post("/admin/coin-packages", json=package(), headers=headers())
        assert duplicate.status_code == 409
        edited = client.put(
            f"/admin/coin-packages/{package_id}",
            json=package(price_uzs=72000),
            headers=headers(),
        )
        assert edited.status_code == 200
        assert edited.json()["price_uzs"] == 72000
        inactive = client.post(f"/admin/coin-packages/{package_id}/deactivate", headers=headers())
        assert inactive.json()["is_active"] is False
        active_list = client.get("/admin/coin-packages?active_only=true", headers=headers()).json()
        assert active_list == []
        assert client.post(f"/admin/coin-packages/{package_id}/activate", headers=headers()).json()["is_active"] is True
    finally:
        engine.dispose()


def test_inactive_package_is_excluded_from_new_promotions_and_history_survives(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        package_id = client.post("/admin/coin-packages", json=package(), headers=headers()).json()["id"]
        created_promotion = client.post(
            "/admin/coin-promotions", json=promotion(package_id), headers=headers(),
        )
        assert created_promotion.status_code == 201

        db = sessions()
        db.add(Order(
            order_number="12345678", telegram_id=42, product_id=package_id,
            product_title="840 Coins", coins_amount=840, price_uzs=Decimal("60000"),
            locked_price=Decimal("60000"), status="COMPLETED",
        ))
        db.commit()
        db.close()

        client.post(f"/admin/coin-packages/{package_id}/deactivate", headers=headers())
        assert client.get("/admin/coin-packages?active_only=true", headers=headers()).json() == []
        blocked = client.post("/admin/coin-promotions", json=promotion(package_id), headers=headers())
        assert blocked.status_code == 422

        db = sessions()
        assert db.query(Order).filter_by(product_id=package_id, status="COMPLETED").count() == 1
        assert db.query(CoinPromotion).filter_by(coin_package_id=package_id).count() == 1
        db.close()
    finally:
        engine.dispose()


def test_validation_and_scope_duplicate_rules(monkeypatch):
    client, _sessions, engine = build(monkeypatch)
    try:
        assert client.post("/admin/coin-packages", json=package(coin_amount=0), headers=headers()).status_code == 422
        assert client.post("/admin/coin-packages", json=package(price_uzs=0), headers=headers()).status_code == 422
        assert client.post("/admin/coin-packages", json=package(scope="INVALID"), headers=headers()).status_code == 422
        assert client.post("/admin/coin-packages", json=package(), headers=headers()).status_code == 201
        assert client.post("/admin/coin-packages", json=package(scope="JAPAN"), headers=headers()).status_code == 201
    finally:
        engine.dispose()


def test_admin_creates_player_and_manager_with_name_and_price(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        player = client.post(
            "/admin/coin-packages",
            json={
                "product_type": "PLAYER", "name": "Lionel Messi",
                "price_uzs": 120000, "scope": "ANDROID", "is_active": True,
            },
            headers=headers(),
        )
        assert player.status_code == 201
        assert player.json()["product_type"] == "PLAYER"
        assert player.json()["name"] == "Lionel Messi"
        assert player.json()["coin_amount"] is None
        assert player.json()["scope"] == "ALL"

        manager = client.post(
            "/admin/coin-packages",
            json={
                "product_type": "MANAGER", "name": "Pep Guardiola",
                "price_uzs": 90000, "is_active": True,
            },
            headers=headers(),
        )
        assert manager.status_code == 201
        assert manager.json()["product_type"] == "MANAGER"

        duplicate = client.post(
            "/admin/coin-packages",
            json={
                "product_type": "PLAYER", "name": "lionel messi",
                "price_uzs": 125000, "is_active": True,
            },
            headers=headers(),
        )
        assert duplicate.status_code == 409

        db = sessions()
        stored = db.get(Product, player.json()["id"])
        assert stored.category == "PLAYERS"
        assert stored.coins_amount is None
        db.close()
    finally:
        engine.dispose()


def test_named_product_cannot_be_used_for_coin_promotion(monkeypatch):
    client, _sessions, engine = build(monkeypatch)
    try:
        item_id = client.post(
            "/admin/coin-packages",
            json={
                "product_type": "PLAYER", "name": "Neymar Jr",
                "price_uzs": 100000, "is_active": True,
            },
            headers=headers(),
        ).json()["id"]
        blocked = client.post(
            "/admin/coin-promotions", json=promotion(item_id), headers=headers(),
        )
        assert blocked.status_code == 422
        assert "Only coin products" in blocked.json()["detail"]
    finally:
        engine.dispose()


def test_startup_seed_never_overwrites_admin_price_or_status(monkeypatch):
    _client, sessions, engine = build(monkeypatch)
    try:
        db = sessions()
        db.add(Product(
            title="260 Coins", category="ANDROID_COINS", platform="android",
            coins_amount=260, price_uzs=Decimal("19000"), is_active=False,
        ))
        db.commit()
        seed_products(db)
        product = db.query(Product).filter_by(category="ANDROID_COINS", coins_amount=260).one()
        assert float(product.price_uzs) == 19000
        assert product.is_active is False
        db.close()
    finally:
        engine.dispose()
