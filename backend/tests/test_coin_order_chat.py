import hashlib, hmac, json, time
from datetime import datetime, timedelta, timezone
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
from app.models.coin_order_message import CoinOrderMessage
from app.models.order import Order
from app.models.wheel import WheelCoinOrder, WheelSpin
from app.models.user import User
from app.models.coin_credential import CoinCredentialAccessAudit, CoinCredentialAccessGrant, CoinOrderCredential
from app.crud.coin_credentials import store_credentials
from app.routers import coin_order_chat, internal_wallet
from app.services import coin_order_notifications


def auth(user_id):
    values={"auth_date":str(int(time.time())),"user":json.dumps({"id":user_id,"first_name":"User"},separators=(",",":"))}
    check="\n".join(f"{k}={v}" for k,v in sorted(values.items())); secret=hmac.new(b"WebAppData",b"token",hashlib.sha256).digest()
    values["hash"]=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data":urlencode(values)}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(telegram_auth,"BOT_TOKEN","token"); monkeypatch.setattr(internal_wallet,"INTERNAL_API_KEY","key")
    monkeypatch.setattr(config,"COIN_CREDENTIAL_ENCRYPTION_KEY","MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine,tables=[User.__table__,Order.__table__,WheelSpin.__table__,WheelCoinOrder.__table__,CoinOrderMessage.__table__,CoinOrderCredential.__table__,CoinCredentialAccessAudit.__table__,CoinCredentialAccessGrant.__table__])
    factory=sessionmaker(bind=engine); db=factory()
    db.add_all([User(telegram_id=42,first_name="A"),User(telegram_id=99,first_name="B"),
        Order(id=1,telegram_id=42,product_id=1,product_title="130",coins_amount=130,price_uzs=Decimal("1"),status="WAITING_OTP"),
        WheelSpin(id=1,telegram_id=42,spin_type="FREE",reward_code="coin_130",reward_type="COIN_ORDER",reward_amount=130,global_spin_number=1,status="COMPLETED")])
    db.flush(); db.add(WheelCoinOrder(id=2,spin_id=1,telegram_id=42,coin_amount=130,status="WAITING_OTP")); db.flush()
    store_credentials(db,"SHOP",1,"user@example.com","shop-secret")
    store_credentials(db,"WHEEL",2,"user@example.com","wheel-secret")
    db.commit(); db.close()
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


def test_operator_confirmation_unlocks_otp_and_notifies_once(client, monkeypatch):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}
    notifications=[]
    def notify(db, kind, order_id):
        notifications.append((kind, order_id))
        db.get(Order, order_id).otp_notification_status = "SENT"
        db.commit()
        return type("Result", (), {"status": "SENT", "sent": True})()
    monkeypatch.setattr(coin_order_notifications, "send_coin_otp_user_notification", notify)
    db=sessions()
    try:
        db.get(Order,1).status="WAITING_OPERATOR"; db.commit()
    finally: db.close()
    assert http.post("/coin-order-chat/SHOP/1/messages",json={"message":"482193"},headers=auth(42)).status_code==409
    opened=http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"OTP_SENT"},headers=internal)
    assert opened.status_code==200 and opened.json()["status"]=="WAITING_OTP"
    repeated=http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"OTP_SENT"},headers=internal)
    assert repeated.status_code==409
    assert notifications==[("SHOP",1)]
    messages=http.get("/coin-order-chat/SHOP/1/messages",headers=auth(42)).json()
    assert messages["unread_count"]==1
    assert messages["data"][-1]["sender"]=="SYSTEM"
    assert len([item for item in messages["data"] if item["sender"]=="SYSTEM"])==1
    assert "6 xonali kodni shu chatga yuboring" in messages["data"][-1]["message"]
    invalid=http.post("/coin-order-chat/SHOP/1/messages",json={"message":"hello"},headers=auth(42))
    assert invalid.status_code==400
    valid=http.post("/coin-order-chat/SHOP/1/messages",json={"message":"482193"},headers=auth(42))
    assert valid.json()["status"]=="OTP_SUBMITTED"


def test_stale_sending_allows_otp_action_retry(client, monkeypatch):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}; calls=[]
    db=sessions()
    try:
        order=db.get(Order,1); order.status="WAITING_OTP"; order.otp_notification_status="SENDING"
        order.otp_notification_attempted_at=datetime.now(timezone.utc)-timedelta(minutes=10)
        db.commit()
    finally: db.close()
    monkeypatch.setattr(coin_order_notifications.config,"COIN_OTP_NOTIFICATION_STALE_SECONDS",300)
    monkeypatch.setattr(coin_order_notifications,"send_coin_otp_user_notification",
        lambda db,kind,order_id: (calls.append((kind,order_id)) or type("Result",(),{"status":"SENT","sent":True})()))
    retried=http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"OTP_SENT"},headers=internal)
    assert retried.status_code==200 and retried.json()["notification_status"]=="SENT"
    assert calls==[("SHOP",1)]


def test_credentials_decrypt_audit_and_terminal_cleanup_are_irreversible(client):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}
    opened=http.post("/coin-order-chat/internal/SHOP/1/credential-grant",json={"admin_id":7,"session_id":"s1"},headers=internal)
    assert opened.status_code==200
    view_path=opened.json()["view_path"]
    assert "shop-secret" not in http.get(view_path).text
    assert http.post(view_path,data={"init_data":auth(8)["X-Telegram-Init-Data"]}).status_code==410
    view=http.post(view_path,data={"init_data":auth(7)["X-Telegram-Init-Data"]})
    assert view.status_code==200 and "shop-secret" in view.text
    assert http.post(view_path,data={"init_data":auth(7)["X-Telegram-Init-Data"]}).status_code==410
    assert http.post("/coin-order-chat/SHOP/1/messages",json={"message":"482193"},headers=auth(42)).json()["status"]=="OTP_SUBMITTED"
    assert http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"ACCEPT_CODE"},headers=internal).json()["status"]=="PENDING"
    assert http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"CLAIM"},headers=internal).status_code==200
    assert http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"COMPLETE"},headers=internal).status_code==200
    assert http.post("/coin-order-chat/internal/SHOP/1/credential-grant",json={"admin_id":7},headers=internal).status_code==410
    db=sessions()
    try:
        assert db.query(CoinOrderCredential).filter_by(order_type="SHOP",order_id=1).first() is None
        assert db.query(CoinOrderMessage).filter_by(order_type="SHOP",order_id=1).one().message=="OTP qabul qilindi"
        assert db.query(CoinCredentialAccessAudit).filter_by(admin_id=7,result="OPENED").count()==1
    finally: db.close()


def test_rejected_wheel_order_destroys_credentials_and_redacts_otp(client):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}
    http.post("/coin-order-chat/WHEEL/2/messages",json={"message":"654321"},headers=auth(42))
    http.post("/coin-order-chat/internal/WHEEL/2/action",json={"admin_id":8,"action":"ACCEPT_CODE"},headers=internal)
    assert http.post("/coin-order-chat/internal/WHEEL/2/action",json={"admin_id":8,"action":"REJECT"},headers=internal).status_code==200
    db=sessions()
    try:
        assert db.query(CoinOrderCredential).filter_by(order_type="WHEEL",order_id=2).first() is None
        assert db.query(CoinOrderMessage).filter_by(order_type="WHEEL",order_id=2).one().message=="OTP qabul qilindi"
    finally: db.close()
