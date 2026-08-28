from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all foreign-key targets
from app.core.database import Base
from app.crud.order import approve_order
from app.models.order import Order
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.services.coin_order_ticket_bonus import coin_order_ticket_bonus_amount


@pytest.fixture()
def sessions():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(telegram_id=42, first_name="Player"))
        db.add_all([
            Order(
                id=1,
                order_number="10000001",
                telegram_id=42,
                product_id=10,
                product_title="260 Coin",
                product_type="COIN",
                coins_amount=260,
                price_uzs=Decimal("19000"),
                locked_price=Decimal("19000"),
                status="CLAIMED",
                claimed_by=700,
            ),
            Order(
                id=2,
                order_number="10000002",
                telegram_id=42,
                product_id=11,
                product_title="Manager",
                product_type="MANAGER",
                coins_amount=999,
                price_uzs=Decimal("5000"),
                locked_price=Decimal("5000"),
                status="CLAIMED",
                claimed_by=700,
            ),
        ])
        db.commit()
    return factory


def test_completed_coin_order_awards_ten_percent_ticket_once(sessions):
    with sessions() as db:
        completed = approve_order(db, 1, 700)
        assert completed.status == "COMPLETED"
        assert completed._ticket_bonus_awarded == 26
        assert completed._ticket_balance == 26

        replay = approve_order(db, 1, 700)
        assert replay == "already_completed"

    with sessions() as db:
        assert db.get(GameTicketWallet, 42).tournament_tickets == 26
        ledger = db.query(GameTicketLedger).one()
        assert ledger.operation == "COIN_ORDER_BONUS"
        assert ledger.amount == 26
        assert ledger.idempotency_key == "coin-order-ticket-bonus:1"
        assert ledger.metadata_json == {
            "order_id": 1,
            "coin_amount": 260,
            "bonus_percent": 10,
        }


def test_non_coin_product_never_awards_ticket(sessions):
    with sessions() as db:
        completed = approve_order(db, 2, 700)
        assert completed.status == "COMPLETED"
        assert completed._ticket_bonus_awarded == 0
        assert completed._ticket_balance is None
        assert db.query(GameTicketLedger).count() == 0
        assert db.get(GameTicketWallet, 42) is None


def test_ticket_bonus_rounds_down_to_a_whole_ticket():
    assert coin_order_ticket_bonus_amount(260) == 26
    assert coin_order_ticket_bonus_amount(265) == 26
    assert coin_order_ticket_bonus_amount(9) == 0
