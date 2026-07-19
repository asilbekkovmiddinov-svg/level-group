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
from app.models.coin_promotion import CoinPromotion
from app.models.product import Product
from app.routers.coin_promotion_admin import router


def init_data(telegram_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Coin Admin"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def headers(telegram_id: int = 9001) -> dict:
    return {"X-Telegram-Init-Data": init_data(telegram_id)}


def build(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Product.__table__, CoinPromotion.__table__])
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
    db = sessions()
    db.add(Product(
        id=7, title="130 Coins", category="ANDROID_COINS", platform="android",
        coins_amount=130, price_uzs=25000, is_active=True,
    ))
    db.commit()
    db.close()
    return TestClient(app), sessions


def payload(**extra) -> dict:
    now = datetime.now(timezone.utc)
    data = {
        "coin_package_id": 7,
        "title": "Flash 130",
        "original_price": 25000,
        "promotion_price": 15000,
        "total_quantity": 10,
        "per_user_limit": 2,
        "start_at": (now - timedelta(minutes=5)).isoformat(),
        "end_at": (now + timedelta(hours=2)).isoformat(),
    }
    data.update(extra)
    return data


def test_admin_auth_and_crud(monkeypatch):
    client, _ = build(monkeypatch)
    assert client.get("/admin/coin-promotions").status_code == 401
    assert client.get("/admin/coin-promotions", headers=headers(7001)).status_code == 403

    created = client.post("/admin/coin-promotions", json=payload(), headers=headers())
    assert created.status_code == 201
    item = created.json()
    assert item["status"] == "DRAFT"
    assert item["coin_package"] == {
        "id": 7, "title": "130 Coins", "category": "ANDROID_COINS",
        "coin_amount": 130, "price": 25000.0,
    }
    assert item["reserved_quantity"] == item["sold_quantity"] == 0
    assert item["remaining_quantity"] == 10

    promotion_id = item["id"]
    listed = client.get("/admin/coin-promotions", headers=headers()).json()
    assert [entry["id"] for entry in listed] == [promotion_id]
    assert client.get(f"/admin/coin-promotions/{promotion_id}", headers=headers()).status_code == 200

    updated = client.put(
        f"/admin/coin-promotions/{promotion_id}",
        json=payload(title="Updated Flash", promotion_price=14000, total_quantity=12),
        headers=headers(),
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated Flash"
    assert updated.json()["promotion_price"] == 14000
    assert updated.json()["remaining_quantity"] == 12


def test_lifecycle_delete_and_restore(monkeypatch):
    client, _ = build(monkeypatch)
    promotion_id = client.post("/admin/coin-promotions", json=payload(), headers=headers()).json()["id"]
    expected = [
        ("activate", "ACTIVE"),
        ("pause", "PAUSED"),
        ("deactivate", "DRAFT"),
    ]
    for action, status in expected:
        result = client.post(f"/admin/coin-promotions/{promotion_id}/{action}", headers=headers())
        assert result.status_code == 200
        assert result.json()["status"] == status

    deleted = client.delete(f"/admin/coin-promotions/{promotion_id}", headers=headers())
    assert deleted.json()["status"] == "DELETED"
    assert client.get(f"/admin/coin-promotions/{promotion_id}", headers=headers()).status_code == 404
    assert client.get("/admin/coin-promotions", headers=headers()).json()[0]["status"] == "DELETED"
    restored = client.post(f"/admin/coin-promotions/{promotion_id}/restore", headers=headers())
    assert restored.status_code == 200
    assert restored.json()["status"] == "DRAFT"


def test_validation_and_authoritative_inventory(monkeypatch):
    client, sessions = build(monkeypatch)
    for invalid in (
        payload(promotion_price=25000),
        payload(total_quantity=0),
        payload(
            start_at=datetime.now(timezone.utc).isoformat(),
            end_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        ),
    ):
        assert client.post("/admin/coin-promotions", json=invalid, headers=headers()).status_code == 422

    assert client.post(
        "/admin/coin-promotions", json=payload(coin_package_id=999), headers=headers(),
    ).status_code == 422

    created = client.post("/admin/coin-promotions", json=payload(), headers=headers()).json()
    db = sessions()
    promotion = db.get(CoinPromotion, created["id"])
    promotion.reserved_quantity = 3
    promotion.sold_quantity = 2
    db.commit()
    db.close()
    invalid_total = client.put(
        f"/admin/coin-promotions/{created['id']}", json=payload(total_quantity=4), headers=headers(),
    )
    assert invalid_total.status_code == 422
    detail = client.get(f"/admin/coin-promotions/{created['id']}", headers=headers()).json()
    assert detail["reserved_quantity"] == 3
    assert detail["sold_quantity"] == 2
    assert detail["remaining_quantity"] == 5
