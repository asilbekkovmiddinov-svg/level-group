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

from app.core import telegram_auth
from app.core.database import Base, get_db
from app.crud import wheel
from app.models.user import User
from app.models.wheel import WheelCoinOrder, WheelSpin
from app.routers import wheel as wheel_router


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


def headers(telegram_id: int):
    return {"X-Telegram-Init-Data": make_init_data(telegram_id)}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, WheelSpin.__table__, WheelCoinOrder.__table__],
    )
    session_factory = sessionmaker(bind=engine)
    setup = session_factory()
    setup.add_all(
        [
            User(telegram_id=42, first_name="Ali"),
            User(telegram_id=99, first_name="Vali"),
            WheelSpin(
                id=1,
                telegram_id=42,
                spin_type=wheel.SPIN_TYPE_FREE,
                reward_code="coin_130",
                reward_type=wheel.REWARD_TYPE_COIN_ORDER,
                reward_amount=Decimal("130"),
                global_spin_number=1,
                status=wheel.STATUS_COMPLETED,
            ),
            WheelSpin(
                id=2,
                telegram_id=42,
                spin_type=wheel.SPIN_TYPE_AD,
                reward_code="coin_2000_jackpot",
                reward_type=wheel.REWARD_TYPE_COIN_ORDER,
                reward_amount=Decimal("2000"),
                global_spin_number=2,
                status=wheel.STATUS_COMPLETED,
            ),
        ]
    )
    setup.commit()
    for spin_id, amount in ((1, 130), (2, 2000)):
        spin = setup.get(WheelSpin, spin_id)
        wheel.create_coin_order(setup, spin, 42, None, "Ali", amount)
    setup.close()

    app = FastAPI()
    app.include_router(wheel_router.router)

    def session_dependency():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = session_dependency
    http = TestClient(app)
    yield http, session_factory
    engine.dispose()


def test_130_and_2000_rewards_create_waiting_details_orders(client):
    _http, sessions = client
    db = sessions()
    try:
        orders = db.query(WheelCoinOrder).order_by(WheelCoinOrder.spin_id).all()
        assert [(order.coin_amount, order.status) for order in orders] == [
            (130, wheel.STATUS_WAITING_DETAILS),
            (2000, wheel.STATUS_WAITING_DETAILS),
        ]
    finally:
        db.close()


def test_pending_restore_details_ownership_and_duplicate_contract(client):
    http, _sessions = client
    assert http.get("/wheel/coin-order/pending").status_code == 401

    pending = http.get("/wheel/coin-order/pending", headers=headers(42))
    assert pending.status_code == 200
    assert pending.json()["data"]["spin_id"] == 2
    assert pending.json()["data"]["status"] == wheel.STATUS_WAITING_DETAILS

    body = {
        "spin_id": 1,
        "konami_login": "player@example.com",
        "konami_password": "one-time-secret",
        "platform": "Android",
        "region": "Global",
    }
    assert http.post("/wheel/coin-order/details", json=body).status_code == 401
    assert http.post(
        "/wheel/coin-order/details", json=body, headers=headers(99)
    ).status_code == 403

    completed = http.post(
        "/wheel/coin-order/details", json=body, headers=headers(42)
    )
    assert completed.status_code == 200
    assert completed.json()["data"]["status"] == wheel.STATUS_PENDING
    assert completed.json()["data"]["platform"] == "Android"

    duplicate = http.post(
        "/wheel/coin-order/details", json=body, headers=headers(42)
    )
    assert duplicate.status_code == 409

    spoofed = {**body, "spin_id": 2, "telegram_id": 99}
    assert http.post(
        "/wheel/coin-order/details", json=spoofed, headers=headers(42)
    ).status_code == 422

