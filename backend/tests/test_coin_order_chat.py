import hashlib, hmac, json, time
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
from app.models.coin_order_message import CoinOrderMessage
from app.models.order import Order
from app.models.wheel import WheelCoinOrder, WheelSpin
from app.models.user import User
from app.routers import coin_order_chat, internal_wallet


def auth(user_id):
    values={"auth_date":str(int(time.time())),"user":json.dumps({"id":user_id,"first_name":"User"},separators=(",",":"))}
    check="\n".join(f"{k}={v}" for k,v in sorted(values.items())); secret=hmac.new(b"WebAppData",b"token",hashlib.sha256).digest()
    values["hash"]=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data":urlencode(values)}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(telegram_auth,"BOT_TOKEN","token"); monkeypatch.setattr(internal_wallet,"INTERNAL_API_KEY","key")
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine,tables=[User.__table__,Order.__table__,WheelSpin.__table__,WheelCoinOrder.__table__,CoinOrderMessage.__table__])
    factory=sessionmaker(bind=engine); db=factory()
    db.add_all([User(telegram_id=42,first_name="A"),User(telegram_id=99,first_name="B"),
        Order(id=1,telegram_id=42,product_id=1,product_title="130",coins_amount=130,price_uzs=Decimal("1"),status="WAITING_OTP"),
        WheelSpin(id=1,telegram_id=42,spin_type="FREE",reward_code="coin_130",reward_type="COIN_ORDER",reward_amount=130,global_spin_number=1,status="COMPLETED")])
    db.flush(); db.add(WheelCoinOrder(id=2,spin_id=1,telegram_id=42,coin_amount=130,status="WAITING_OTP")); db.commit(); db.close()
    app=FastAPI(); app.include_router(coin_order_chat.router)
    def dep():
        session=factory()
        try: yield session
        finally: session.close()
    app.dependency_overrides[get_db]=dep
    yield TestClient(app),factory


def test_user_operator_message_otp_reload_unread_and_ownership(client):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}
    assert http.post("/coin-order-chat/SHOP/1/messages",json={"message":"482193"},headers=auth(99)).status_code==403
    sent=http.post("/coin-order-chat/SHOP/1/messages",json={"message":"482193"},headers=auth(42))
    assert sent.status_code==200 and sent.json()["status"]=="OTP_SUBMITTED"
    loaded=http.get("/coin-order-chat/SHOP/1/messages",headers=auth(42)).json()
    assert loaded["data"][0]["message"]=="482193"
    active=http.get("/coin-order-chat/internal/active",headers=internal).json()["data"]
    assert next(x for x in active if x["order_type"]=="SHOP")["unread_count"]==1
    assert http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"ACCEPT_CODE"},headers=internal).json()["status"]=="PENDING"
    reply=http.post("/coin-order-chat/internal/SHOP/1/messages",json={"admin_id":7,"message":"Kod qabul qilindi"},headers=internal)
    assert reply.status_code==200
    assert http.get("/coin-order-chat/SHOP/1/messages",headers=auth(42)).json()["unread_count"]==1
    assert http.post("/coin-order-chat/SHOP/1/read",headers=auth(42)).json()["read"]==1


def test_wheel_wrong_code_returns_to_waiting_otp(client):
    http,_=client; internal={"X-Internal-Api-Key":"key"}
    assert http.post("/coin-order-chat/WHEEL/2/messages",json={"message":"111111"},headers=auth(42)).json()["status"]=="OTP_SUBMITTED"
    result=http.post("/coin-order-chat/internal/WHEEL/2/action",json={"admin_id":7,"action":"WRONG_CODE"},headers=internal)
    assert result.json()["status"]=="WAITING_OTP"
