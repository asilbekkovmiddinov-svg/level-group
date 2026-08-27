import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import *  # noqa: F401,F403 - register foreign keys
from app.models.shop import ShopPurchase, ShopSettings
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.routers.internal_shop import router as internal_shop_router
from app.routers.internal_wallet import require_internal_api_key
from app.services import shop
from app.services.shop import (
    ShopIdempotencyConflict,
    ShopInsufficientBalance,
    buy_arena_tickets,
    buy_efc,
    catalog,
    update_settings,
)


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(shop.config, "SHOP_EFC_PRICE_UZS", shop.Decimal("1000"))
    monkeypatch.setattr(shop.config, "SHOP_ARENA_TICKET_PRICE_EFC", shop.Decimal("10"))
    monkeypatch.setattr(shop.config, "SHOP_MAX_EFC_PER_PURCHASE", 10000)
    monkeypatch.setattr(shop.config, "SHOP_MAX_TICKETS_PER_PURCHASE", 100)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(telegram_id=42, first_name="Ali"),
        Wallet(
            telegram_id=42,
            uzs_balance=100000,
            efc_balance=20,
            locked_uzs=0,
            locked_efc=0,
            locked_reward_efc=0,
        ),
        GameTicketWallet(telegram_id=42, tournament_tickets=1),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()


def test_buy_efc_is_atomic_and_idempotent(db):
    first = buy_efc(
        db,
        telegram_id=42,
        efc_amount=50,
        idempotency_key="buy-efc-once",
    )
    replay = buy_efc(
        db,
        telegram_id=42,
        efc_amount=50,
        idempotency_key="buy-efc-once",
    )
    wallet = db.get(Wallet, 42)
    assert first["purchase_id"] == replay["purchase_id"]
    assert float(wallet.uzs_balance) == 50000
    assert float(wallet.efc_balance) == 70
    assert db.query(ShopPurchase).count() == 1
    assert db.query(Transaction).filter(
        Transaction.type.in_(["SHOP_EFC_PURCHASE", "SHOP_EFC_CREDIT"])
    ).count() == 2


def test_reused_idempotency_key_with_other_payload_is_rejected(db):
    buy_efc(db, telegram_id=42, efc_amount=10, idempotency_key="same-key")
    with pytest.raises(ShopIdempotencyConflict):
        buy_efc(db, telegram_id=42, efc_amount=11, idempotency_key="same-key")


def test_insufficient_uzs_does_not_credit_efc(db):
    with pytest.raises(ShopInsufficientBalance):
        buy_efc(db, telegram_id=42, efc_amount=101, idempotency_key="too-big")
    wallet = db.get(Wallet, 42)
    assert float(wallet.uzs_balance) == 100000
    assert float(wallet.efc_balance) == 20
    assert db.query(ShopPurchase).count() == 0


def test_buy_arena_ticket_deducts_efc_and_adds_ticket_once(db):
    first = buy_arena_tickets(
        db,
        telegram_id=42,
        quantity=2,
        idempotency_key="tickets-once",
    )
    replay = buy_arena_tickets(
        db,
        telegram_id=42,
        quantity=2,
        idempotency_key="tickets-once",
    )
    wallet = db.get(Wallet, 42)
    tickets = db.get(GameTicketWallet, 42)
    assert first["purchase_id"] == replay["purchase_id"]
    assert float(wallet.efc_balance) == 0
    assert tickets.tournament_tickets == 3
    assert db.query(GameTicketLedger).filter(
        GameTicketLedger.operation == "SHOP_PURCHASE"
    ).count() == 1
    assert db.query(Transaction).filter(
        Transaction.type == "SHOP_ARENA_TICKET_PURCHASE"
    ).count() == 1


def test_insufficient_efc_does_not_add_ticket(db):
    with pytest.raises(ShopInsufficientBalance):
        buy_arena_tickets(
            db,
            telegram_id=42,
            quantity=3,
            idempotency_key="tickets-too-many",
        )
    assert db.get(Wallet, 42).efc_balance == 20
    assert db.get(GameTicketWallet, 42).tournament_tickets == 1
    assert db.query(GameTicketLedger).count() == 0


def test_admin_prices_are_persisted_and_used_by_catalog(db):
    value = update_settings(
        db,
        admin_id=42,
        efc_price_uzs=750,
        ticket_price_efc=7.5,
    )
    assert float(value.efc_price_uzs) == 750
    assert float(value.ticket_price_efc) == 7.5
    assert value.updated_by == 42
    assert db.query(ShopSettings).count() == 1
    data = catalog(db, 42)
    assert data["efc_price_uzs"] == 750
    assert data["ticket_price_efc"] == 7.5


def test_every_shop_route_requires_internal_auth():
    assert internal_shop_router.routes
    for route in internal_shop_router.routes:
        dependencies = {item.call for item in route.dependant.dependencies}
        assert require_internal_api_key in dependencies


def test_purchase_uses_admin_price_snapshot(db):
    update_settings(
        db,
        admin_id=42,
        efc_price_uzs=500,
        ticket_price_efc=4,
    )
    efc = buy_efc(
        db,
        telegram_id=42,
        efc_amount=10,
        idempotency_key="admin-priced-efc",
    )
    assert efc["uzs_cost"] == 5000
    purchase = db.get(ShopPurchase, efc["purchase_id"])
    assert float(purchase.efc_price_uzs) == 500

    update_settings(
        db,
        admin_id=42,
        efc_price_uzs=900,
        ticket_price_efc=4,
    )
    db.refresh(purchase)
    assert float(purchase.efc_price_uzs) == 500

    tickets = buy_arena_tickets(
        db,
        telegram_id=42,
        quantity=2,
        idempotency_key="admin-priced-tickets",
    )
    assert tickets["efc_cost"] == 8
    ticket_purchase = db.get(ShopPurchase, tickets["purchase_id"])
    assert float(ticket_purchase.ticket_price_efc) == 4
