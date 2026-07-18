import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config, telegram_auth
from app.core.database import Base, get_db
from app.models.order import Order
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.models.coin_credential import CoinOrderCredential
from app.models.coin_order_message import CoinOrderMessage
from app.routers import order as order_router
from app.routers import product as product_router
from app.routers import internal_wallet
from app.crud import order as order_crud
from sqlalchemy.exc import SQLAlchemyError


def make_init_data(telegram_id: int):
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": telegram_id, "first_name": f"User {telegram_id}"},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def headers(telegram_id: int, key: str | None = None):
    result = {"X-Telegram-Init-Data": make_init_data(telegram_id)}
    if key:
        result["Idempotency-Key"] = key
    return result


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(internal_wallet, "INTERNAL_API_KEY", "internal-test-key")
    monkeypatch.setattr(config, "COIN_CREDENTIAL_ENCRYPTION_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Wallet.__table__,
            Product.__table__,
            Order.__table__,
            Transaction.__table__,
            CoinOrderCredential.__table__,
            CoinOrderMessage.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine)
    setup = session_factory()
    setup.add_all(
        [
            User(telegram_id=42, first_name="Ali"),
            User(telegram_id=99, first_name="Vali"),
            User(telegram_id=5_000_000_001, first_name="Big ID"),
            Wallet(
                telegram_id=42,
                uzs_balance=Decimal("100000"),
                locked_uzs=0,
                efc_balance=0,
                locked_efc=0,
            ),
            Wallet(
                telegram_id=99,
                uzs_balance=Decimal("100000"),
                locked_uzs=0,
                efc_balance=0,
                locked_efc=0,
            ),
            Wallet(
                telegram_id=5_000_000_001,
                uzs_balance=Decimal("100000"),
                locked_uzs=0,
                efc_balance=0,
                locked_efc=0,
            ),
            Product(
                id=7,
                title="130 Coins",
                category="ANDROID_COINS",
                platform="android",
                coins_amount=130,
                price_uzs=Decimal("25000"),
                is_active=True,
            ),
        ]
    )
    setup.commit()
    setup.close()

    app = FastAPI()
    app.include_router(product_router.router)
    app.include_router(order_router.router)

    def session_dependency():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = session_dependency
    test_client = TestClient(app)
    yield test_client, session_factory
    engine.dispose()


def test_coin_endpoints_require_verified_init_data(client):
    http, _sessions = client
    assert http.get("/products/active").status_code == 401
    assert http.post("/orders/create", json={"product_id": 7}).status_code == 401
    assert http.get("/orders/user").status_code == 401


def test_shop_admin_endpoints_require_internal_api_key(client):
    http, _sessions = client
    for path in ("/products/all", "/orders/all", "/orders/pending", "/orders/claimed"):
        assert http.get(path).status_code == 403
        assert http.get(path, headers={"X-Internal-Api-Key": "internal-test-key"}).status_code == 200

    assert http.post("/orders/1/claim", json={"admin_id": 7}).status_code == 403
    assert http.post("/orders/1/approve", json={"admin_id": 7}).status_code == 403
    assert http.post(
        "/orders/1/reject", json={"admin_id": 7, "reason": "test"}
    ).status_code == 403
    assert http.post("/orders/cancel/1").status_code == 403


def test_order_identity_history_and_idempotency_are_user_scoped(client):
    http, sessions = client
    body = {"product_id": 7, "region": "Japan", "telegram_id": 99, "konami_login": "u@example.com", "konami_password": "secret", "platform": "Android"}

    first = http.post(
        "/orders/create",
        json=body,
        headers=headers(42, "coin-order-42"),
    )
    replay = http.post(
        "/orders/create",
        json=body,
        headers=headers(42, "coin-order-42"),
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["data"]["status"] == "WAITING_OPERATOR"
    assert first.json()["data"]["id"] == replay.json()["data"]["id"]
    assert first.json()["data"]["telegram_id"] == 42

    db = sessions()
    try:
        assert db.query(Order).count() == 1
        assert db.query(Transaction).filter(Transaction.type == "ORDER_PAYMENT").count() == 1
        assert float(db.get(Wallet, 42).uzs_balance) == 75000
        assert float(db.get(Wallet, 99).uzs_balance) == 100000
    finally:
        db.close()

    owner = http.get("/orders/user", headers=headers(42)).json()["data"]
    other_user = http.get("/orders/user", headers=headers(99)).json()["data"]
    assert len(owner) == 1
    assert other_user == []

    conflict = http.post(
        "/orders/create",
        json={"product_id": 7, "region": "Global", "konami_login": "u@example.com", "konami_password": "secret", "platform": "Android"},
        headers=headers(42, "coin-order-42"),
    )
    assert conflict.status_code == 409


def test_order_create_accepts_telegram_id_above_integer_range(client):
    http, sessions = client
    telegram_id = 5_000_000_001
    response = http.post(
        "/orders/create",
        json={
            "product_id": 7,
            "region": "Global",
            "konami_login": "big-id@example.com",
            "konami_password": "secret",
            "platform": "Android",
        },
        headers=headers(telegram_id, "coin-order-big-telegram-id"),
    )
    assert response.status_code == 200
    assert response.json()["data"]["telegram_id"] == telegram_id
    db = sessions()
    try:
        assert db.query(Order).filter(Order.telegram_id == telegram_id).one()
        assert db.query(Transaction).filter(Transaction.telegram_id == telegram_id).one()
    finally:
        db.close()


def test_idempotency_replay_never_regresses_lifecycle(client):
    http, sessions = client
    body = {"product_id": 7, "region": "Japan", "konami_login": "u@example.com",
        "konami_password": "secret", "platform": "Android"}
    first = http.post("/orders/create", json=body, headers=headers(42, "replay-safe"))
    assert first.json()["data"]["status"] == "WAITING_OPERATOR"
    db = sessions()
    try:
        order = db.get(Order, first.json()["data"]["id"])
        order.status = "COMPLETED"
        db.commit()
    finally:
        db.close()

    replay = http.post("/orders/create", json=body, headers=headers(42, "replay-safe"))
    assert replay.status_code == 200
    assert replay.json()["data"]["status"] == "COMPLETED"
    db = sessions()
    try:
        assert db.get(Order, first.json()["data"]["id"]).status == "COMPLETED"
        assert db.query(Order).count() == 1
        assert db.query(Transaction).filter(Transaction.type == "ORDER_PAYMENT").count() == 1
    finally:
        db.close()


@pytest.mark.parametrize("field,value", [
    ("platform", "iOS"),
    ("konami_login", "other@example.com"),
    ("konami_password", "different-secret"),
])
def test_idempotency_payload_mismatch_returns_409(client, field, value):
    http, _sessions = client
    body = {"product_id": 7, "region": "Global", "konami_login": "u@example.com",
        "konami_password": "secret", "platform": "Android"}
    assert http.post("/orders/create", json=body, headers=headers(42, "full-fingerprint")).status_code == 200
    changed = {**body, field: value}
    assert http.post("/orders/create", json=changed, headers=headers(42, "full-fingerprint")).status_code == 409


def test_order_transaction_rolls_back_all_side_effects(client, monkeypatch):
    http, sessions = client
    monkeypatch.setattr(order_crud, "store_credentials",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("encrypt failed")))
    body = {"product_id": 7, "region": "Global", "konami_login": "u@example.com",
        "konami_password": "secret", "platform": "Android"}
    response = http.post("/orders/create", json=body, headers=headers(42, "rollback-all"))
    assert response.status_code == 500
    db = sessions()
    try:
        assert db.query(Order).count() == 0
        assert db.query(CoinOrderCredential).count() == 0
        assert db.query(CoinOrderMessage).count() == 0
        assert db.query(Transaction).count() == 0
        assert float(db.get(Wallet, 42).uzs_balance) == 100000
    finally:
        db.close()
