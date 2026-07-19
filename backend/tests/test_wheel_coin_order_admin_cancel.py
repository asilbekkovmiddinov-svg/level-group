import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import admin_auth, telegram_auth
from app.core.database import Base, get_db
from app.models.coin_credential import CoinOrderCredential
from app.models.coin_order_message import CoinOrderMessage
from app.models.user import User
from app.models.wheel import WheelCoinOrder, WheelSpin
from app.models.wheel_coin_order_audit import WheelCoinOrderAudit
from app.routers.wheel import router as wheel_router
from app.routers.wheel_coin_order_admin import router as admin_router


def init_data(telegram_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Admin"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def headers(telegram_id: int = 9001) -> dict:
    return {"X-Telegram-Init-Data": init_data(telegram_id)}


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    tables = [
        User.__table__, WheelSpin.__table__, WheelCoinOrder.__table__,
        CoinOrderCredential.__table__, CoinOrderMessage.__table__,
        WheelCoinOrderAudit.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(admin_auth, "ADMIN_TELEGRAM_IDS", frozenset({9001}))

    app = FastAPI()
    app.include_router(wheel_router)
    app.include_router(admin_router)

    def dependency():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = dependency
    db = sessions()
    db.add(User(telegram_id=42, first_name="Legacy User"))
    db.add(WheelSpin(
        id=1, telegram_id=42, spin_type="FREE", reward_code="coin_130",
        reward_type="COIN_ORDER", reward_amount=130, global_spin_number=1,
        status="COMPLETED",
    ))
    db.flush()
    db.add(WheelCoinOrder(
        id=7, spin_id=1, telegram_id=42, coin_amount=130,
        konami_login="legacy@example.com", konami_password="legacy-password",
        status="WAITING_DETAILS",
    ))
    db.flush()
    db.add(CoinOrderCredential(
        order_type="WHEEL", order_id=7,
        email_ciphertext=b"email", email_nonce=b"nonce",
        password_ciphertext=b"password", password_nonce=b"nonce",
    ))
    db.add(CoinOrderMessage(
        order_type="WHEEL", order_id=7, telegram_id=42,
        sender="USER", sender_id=42, message="123456",
    ))
    db.commit()
    db.close()
    return TestClient(app), sessions


def test_verified_admin_cancels_and_pending_no_longer_restores(setup):
    client, sessions = setup
    assert client.get("/wheel/coin-order/pending", headers=headers(42)).json()["data"]["id"] == 7

    response = client.post("/admin/wheel/coin-orders/7/cancel", headers=headers())
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"
    assert client.get("/wheel/coin-order/pending", headers=headers(42)).json()["data"] is None

    db = sessions()
    order = db.get(WheelCoinOrder, 7)
    assert order.status == "CANCELLED"
    assert order.updated_at is not None
    assert order.konami_login is None and order.konami_password is None
    assert db.query(CoinOrderCredential).filter_by(order_type="WHEEL", order_id=7).count() == 0
    assert db.query(CoinOrderMessage).filter_by(order_type="WHEEL", order_id=7).one().message == "OTP qabul qilindi"
    audit = db.query(WheelCoinOrderAudit).one()
    assert (audit.admin_telegram_id, audit.order_id) == (9001, 7)
    assert (audit.old_status, audit.new_status, audit.reason) == (
        "WAITING_DETAILS", "CANCELLED", "Admin cleanup",
    )
    db.close()


def test_cancel_requires_verified_admin(setup):
    client, _ = setup
    assert client.post("/admin/wheel/coin-orders/7/cancel").status_code == 401
    assert client.post("/admin/wheel/coin-orders/7/cancel", headers=headers(7001)).status_code == 403


@pytest.mark.parametrize("order_status", ["COMPLETED", "CANCELLED", "REJECTED"])
def test_terminal_order_cannot_be_cancelled(setup, order_status):
    client, sessions = setup
    db = sessions()
    db.get(WheelCoinOrder, 7).status = order_status
    db.commit()
    db.close()

    response = client.post("/admin/wheel/coin-orders/7/cancel", headers=headers())
    assert response.status_code == 409
    db = sessions()
    assert db.get(WheelCoinOrder, 7).status == order_status
    assert db.query(WheelCoinOrderAudit).count() == 0
    db.close()
