import hashlib
import hmac
import json
import threading
import time
import importlib.util
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import telegram_auth
from app.core.database import Base, get_db
from app.crud.order import approve_order, cancel_order, claim_order, create_order, reject_order
from app.models.coin_promotion import CoinPromotion
from app.models.order import Order
from app.models.product import Product
from app.models.referral import Referral, ReferralProfile, ReferralReward
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.routers import internal_wallet
from app.routers.order import router as order_router
from app.routers.product import router as product_router
from app.schemas.order import OrderCreate
from app.services.coin_promotion_timeouts import expire_once


TABLES = [
    User.__table__, Wallet.__table__, Product.__table__, CoinPromotion.__table__,
    Order.__table__, Transaction.__table__, ReferralProfile.__table__, Referral.__table__,
    ReferralReward.__table__,
]


def init_data(telegram_id):
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Buyer", "username": f"buyer{telegram_id}"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def user_headers(telegram_id, key):
    return {"X-Telegram-Init-Data": init_data(telegram_id), "Idempotency-Key": key}


def build(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(internal_wallet, "INTERNAL_API_KEY", "internal-key")
    db = sessions()
    db.add(Product(id=7, title="130 Coins", category="ANDROID_COINS", platform="android", region="GLOBAL", coins_amount=130, price_uzs=25000, is_active=True))
    for telegram_id in range(101, 106):
        db.add(User(telegram_id=telegram_id, first_name="Buyer", username=f"buyer{telegram_id}"))
        db.add(Wallet(telegram_id=telegram_id, uzs_balance=100000, efc_balance=0, locked_uzs=0, locked_efc=0))
    db.commit()
    app = FastAPI()
    app.include_router(product_router)
    app.include_router(order_router)

    def dependency():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = dependency
    return TestClient(app), sessions


def add_promotion(sessions, total=3, per_user_limit=2, status="ACTIVE"):
    now = datetime.now(timezone.utc)
    db = sessions()
    promotion = CoinPromotion(
        title="Limited 130", status=status, coin_package_id=7,
        original_price=25000, promotion_price=15000,
        total_quantity=total, reserved_quantity=0, sold_quantity=0,
        start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
        per_user_limit=per_user_limit,
    )
    db.add(promotion)
    db.commit()
    promotion_id = promotion.id
    db.close()
    return promotion_id


def test_active_promotion_api_locked_price_and_reservation(monkeypatch):
    http, sessions = build(monkeypatch)
    promotion_id = add_promotion(sessions)
    product = http.get("/products/active", headers=user_headers(101, "unused")).json()["data"][0]
    assert product["original_price"] == 25000
    assert product["promotion_price"] == 15000
    assert product["remaining_quantity"] == 3
    assert product["promotion_id"] == promotion_id
    created = http.post("/orders/create", json={"product_id": 7}, headers=user_headers(101, "promo-1"))
    assert created.status_code == 200
    order = created.json()["data"]
    assert order["price_uzs"] == order["locked_price"] == 15000
    assert order["promotion_id"] == promotion_id
    db = sessions()
    promotion = db.get(CoinPromotion, promotion_id)
    assert promotion.reserved_quantity == 1 and promotion.sold_quantity == 0
    assert promotion.remaining_quantity == 2
    assert Decimal(str(db.get(Wallet, 101).uzs_balance)) == Decimal("85000.00")
    db.close()
    refreshed = http.get("/products/active", headers=user_headers(101, "unused-2")).json()["data"][0]
    assert refreshed["remaining_quantity"] == 2


def test_confirm_moves_reserved_to_sold(monkeypatch):
    _http, sessions = build(monkeypatch)
    promotion_id = add_promotion(sessions)
    db = sessions()
    order = create_order(db, OrderCreate(product_id=7), 101, "confirm")
    claim_order(db, order.id, 700)
    completed = approve_order(db, order.id, 700)
    promotion = db.get(CoinPromotion, promotion_id)
    assert completed.status == "COMPLETED"
    assert promotion.reserved_quantity == 0 and promotion.sold_quantity == 1
    assert promotion.remaining_quantity == 2
    db.close()


def test_reject_and_cancel_release_reservation_and_refund_locked_price(monkeypatch):
    _http, sessions = build(monkeypatch)
    promotion_id = add_promotion(sessions)
    db = sessions()
    rejected = create_order(db, OrderCreate(product_id=7), 101, "reject")
    claim_order(db, rejected.id, 700)
    assert reject_order(db, rejected.id, 700, "cancel").status == "REJECTED"
    db.close()
    db = sessions()
    cancelled = create_order(db, OrderCreate(product_id=7), 102, "cancel")
    assert cancel_order(db, cancelled.id, "user cancelled").status == "CANCELLED"
    promotion = db.get(CoinPromotion, promotion_id)
    assert promotion.reserved_quantity == promotion.sold_quantity == 0
    assert promotion.remaining_quantity == 3
    assert Decimal(str(db.get(Wallet, 101).uzs_balance)) == Decimal("100000.00")
    assert Decimal(str(db.get(Wallet, 102).uzs_balance)) == Decimal("100000.00")
    db.close()


def test_timeout_releases_inventory(monkeypatch):
    _http, sessions = build(monkeypatch)
    promotion_id = add_promotion(sessions)
    db = sessions()
    order = create_order(db, OrderCreate(product_id=7), 101, "timeout")
    order.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    db.close()
    assert expire_once(sessions) == 1
    db = sessions()
    assert db.get(Order, order.id).status == "CANCELLED"
    assert db.get(CoinPromotion, promotion_id).remaining_quantity == 3
    db.close()


def test_inactive_or_depleted_promotion_does_not_change_normal_price(monkeypatch):
    _http, sessions = build(monkeypatch)
    add_promotion(sessions, status="PAUSED")
    db = sessions()
    order = create_order(db, OrderCreate(product_id=7), 101, "normal")
    assert order.promotion_id is None
    assert Decimal(str(order.locked_price)) == Decimal("25000")
    assert order.expires_at is None
    db.close()


def test_per_user_limit_prevents_additional_reservation(monkeypatch):
    http, sessions = build(monkeypatch)
    promotion_id = add_promotion(sessions, total=3, per_user_limit=1)
    assert http.post("/orders/create", json={"product_id": 7}, headers=user_headers(101, "limit-1")).status_code == 200
    limited = http.post("/orders/create", json={"product_id": 7}, headers=user_headers(101, "limit-2"))
    assert limited.status_code == 409
    db = sessions()
    assert db.get(CoinPromotion, promotion_id).reserved_quantity == 1
    assert db.query(Order).filter(Order.telegram_id == 101).count() == 1
    db.close()


def test_concurrent_orders_never_oversell_promotion(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine, tables=TABLES)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    db = sessions()
    db.add(Product(id=7, title="130 Coins", category="ANDROID_COINS", coins_amount=130, price_uzs=25000, is_active=True))
    for telegram_id in range(101, 105):
        db.add(User(telegram_id=telegram_id, first_name="Buyer"))
        db.add(Wallet(telegram_id=telegram_id, uzs_balance=100000, efc_balance=0, locked_uzs=0, locked_efc=0))
    db.commit()
    db.close()
    promotion_id = add_promotion(sessions, total=1, per_user_limit=1)
    barrier = threading.Barrier(4)
    results = []

    def create(telegram_id):
        db = sessions()
        try:
            barrier.wait()
            results.append(create_order(db, OrderCreate(product_id=7), telegram_id, f"concurrent-{telegram_id}"))
        finally:
            db.close()

    threads = [threading.Thread(target=create, args=(telegram_id,)) for telegram_id in range(101, 105)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert all(not thread.is_alive() for thread in threads)
    db = sessions()
    promotion = db.get(CoinPromotion, promotion_id)
    promoted_orders = db.query(Order).filter(Order.promotion_id == promotion_id).count()
    assert promotion.reserved_quantity + promotion.sold_quantity <= promotion.total_quantity == 1
    assert promoted_orders == 1
    db.close()
    engine.dispose()


def test_coin_promotion_migration_upgrade_and_downgrade(monkeypatch):
    path = __import__("pathlib").Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260719_coin_promotion_v1.py"
    spec = importlib.util.spec_from_file_location("coin_promotion_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table("products", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table(
        "orders", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("price_uzs", sa.Numeric(18, 2), nullable=False),
    )
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(sa.text("INSERT INTO orders (id, price_uzs) VALUES (1, 25000)"))
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()
        inspector = sa.inspect(connection)
        assert "coin_promotions" in inspector.get_table_names()
        columns = {item["name"]: item for item in inspector.get_columns("orders")}
        assert {"locked_price", "promotion_id", "expires_at", "cancelled_at", "cancel_reason"} <= set(columns)
        assert connection.execute(sa.text("SELECT locked_price FROM orders WHERE id=1")).scalar() == 25000
        migration.downgrade()
        assert "coin_promotions" not in sa.inspect(connection).get_table_names()
        assert "locked_price" not in {item["name"] for item in sa.inspect(connection).get_columns("orders")}
