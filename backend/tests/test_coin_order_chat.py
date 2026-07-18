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
from app.models.wallet import Wallet
from app.models.transaction import Transaction
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
    Base.metadata.create_all(engine,tables=[User.__table__,Wallet.__table__,Transaction.__table__,Order.__table__,WheelSpin.__table__,WheelCoinOrder.__table__,CoinOrderMessage.__table__,CoinOrderCredential.__table__,CoinCredentialAccessAudit.__table__,CoinCredentialAccessGrant.__table__])
    factory=sessionmaker(bind=engine); db=factory()
    db.add_all([User(telegram_id=42,first_name="A"),User(telegram_id=99,first_name="B"),Wallet(telegram_id=42,uzs_balance=Decimal("10"),efc_balance=0,locked_uzs=0,locked_efc=0),
        Order(id=1,telegram_id=42,product_id=1,product_title="130",coins_amount=130,price_uzs=Decimal("1"),status="CLAIMED",claimed_by=7),
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


def test_user_operator_message_reload_unread_and_ownership(client):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}
    assert http.post("/coin-order-chat/SHOP/1/messages",json={"message":"482193"},headers=auth(99)).status_code==403
    sent=http.post("/coin-order-chat/SHOP/1/messages",json={"message":"MyKonami ma’lumotlari"},headers=auth(42))
    assert sent.status_code==200 and sent.json()["status"]=="CLAIMED"
    loaded=http.get("/coin-order-chat/SHOP/1/messages",headers=auth(42)).json()
    assert loaded["data"][0]["message"]=="MyKonami ma’lumotlari"
    active=http.get("/coin-order-chat/internal/active",headers=internal).json()["data"]
    assert next(x for x in active if x["order_type"]=="SHOP")["unread_count"]==1
    reply=http.post("/coin-order-chat/internal/SHOP/1/messages",json={"admin_id":7,"message":"Buyurtma ustida ishlayapman"},headers=internal)
    assert reply.status_code==200
    assert http.get("/coin-order-chat/SHOP/1/messages",headers=auth(42)).json()["unread_count"]==1
    assert http.post("/coin-order-chat/SHOP/1/read",headers=auth(42)).json()["read"]==1


def test_wheel_wrong_code_returns_to_waiting_otp(client):
    http,_=client; internal={"X-Internal-Api-Key":"key"}
    assert http.post("/coin-order-chat/WHEEL/2/messages",json={"message":"111111"},headers=auth(42)).json()["status"]=="OTP_SUBMITTED"
    result=http.post("/coin-order-chat/internal/WHEEL/2/action",json={"admin_id":7,"action":"WRONG_CODE"},headers=internal)
    assert result.json()["status"]=="WAITING_OTP"


def test_shop_claim_opens_plain_order_chat_without_otp_stage(client):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}
    db=sessions()
    try:
        db.get(Order,1).status="WAITING_OPERATOR"; db.commit()
    finally: db.close()
    assert http.post("/coin-order-chat/SHOP/1/messages",json={"message":"482193"},headers=auth(42)).status_code==409
    assert http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"OTP_SENT"},headers=internal).status_code==409
    claimed=http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"CLAIM"},headers=internal)
    assert claimed.status_code==200 and claimed.json()["status"]=="CLAIMED"
    valid=http.post("/coin-order-chat/SHOP/1/messages",json={"message":"Oddiy chat xabari"},headers=auth(42))
    assert valid.status_code==200 and valid.json()["status"]=="CLAIMED"


def test_wheel_stale_sending_allows_otp_action_retry(client, monkeypatch):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}; calls=[]
    db=sessions()
    try:
        order=db.get(WheelCoinOrder,2); order.status="WAITING_OTP"; order.otp_notification_status="SENDING"
        order.otp_notification_attempted_at=datetime.now(timezone.utc)-timedelta(minutes=10)
        db.commit()
    finally: db.close()
    monkeypatch.setattr(coin_order_notifications.config,"COIN_OTP_NOTIFICATION_STALE_SECONDS",300)
    monkeypatch.setattr(coin_order_notifications,"send_coin_otp_user_notification",
        lambda db,kind,order_id: (calls.append((kind,order_id)) or type("Result",(),{"status":"SENT","sent":True})()))
    retried=http.post("/coin-order-chat/internal/WHEEL/2/action",json={"admin_id":7,"action":"OTP_SENT"},headers=internal)
    assert retried.status_code==200 and retried.json()["notification_status"]=="SENT"
    assert calls==[("WHEEL",2)]


def test_terminal_cleanup_removes_legacy_credentials_without_view_endpoint(client):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}
    assert http.post("/coin-order-chat/internal/SHOP/1/credential-grant",json={"admin_id":7},headers=internal).status_code==404
    assert http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"COMPLETE"},headers=internal).status_code==200
    db=sessions()
    try:
        assert db.query(CoinOrderCredential).filter_by(order_type="SHOP",order_id=1).first() is None
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


def test_rejected_shop_order_refunds_wallet_and_commits_cleanup_atomically(client):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}
    rejected=http.post("/coin-order-chat/internal/SHOP/1/action",json={"admin_id":7,"action":"REJECT"},headers=internal)
    assert rejected.status_code==200 and rejected.json()["status"]=="REJECTED"
    db=sessions()
    try:
        assert Decimal(str(db.get(Wallet,42).uzs_balance))==Decimal("11")
        refund=db.query(Transaction).filter_by(telegram_id=42,type="ORDER_REJECT_REFUND").one()
        assert Decimal(str(refund.balance_before))==Decimal("10")
        assert Decimal(str(refund.balance_after))==Decimal("11")
        assert db.query(CoinOrderCredential).filter_by(order_type="SHOP",order_id=1).first() is None
    finally: db.close()


def test_shop_claim_then_user_and_operator_use_only_order_chat(client):
    http,sessions=client; internal={"X-Internal-Api-Key":"key"}
    db=sessions()
    try:
        db.add(Order(id=3,telegram_id=42,product_id=1,product_title="130",coins_amount=130,
            price_uzs=Decimal("1"),platform="ANDROID",region="GLOBAL",status="WAITING_OPERATOR"))
        db.commit()
    finally: db.close()
    claimed=http.post("/coin-order-chat/internal/SHOP/3/action",json={"admin_id":7,"action":"CLAIM"},headers=internal)
    assert claimed.status_code==200 and claimed.json()["status"]=="CLAIMED"
    assert http.post("/coin-order-chat/SHOP/3/messages",json={"message":"Salom operator"},headers=auth(99)).status_code==403
    assert http.post("/coin-order-chat/SHOP/3/messages",json={"message":"Salom operator"},headers=auth(42)).status_code==200
    assert http.post("/coin-order-chat/internal/SHOP/3/messages",json={"admin_id":8,"message":"Begona"},headers=internal).status_code==403
    assert http.post("/coin-order-chat/internal/SHOP/3/messages",json={"admin_id":7,"message":"Qabul qilindi"},headers=internal).status_code==200
    db=sessions()
    try:
        messages=db.query(CoinOrderMessage).filter_by(order_type="SHOP",order_id=3).all()
        assert [item.message for item in messages]==["Salom operator","Qabul qilindi"]
        assert db.query(CoinOrderCredential).filter_by(order_type="SHOP",order_id=3).first() is None
    finally: db.close()
