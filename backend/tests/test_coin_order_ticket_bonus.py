from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all foreign-key targets
from app.core.database import Base
from app.crud.order import approve_order
from app.models.order import Order
from app.models.tournament import (
    Tournament,
    TournamentEntryMode,
    TournamentFormat,
    TournamentGroupMode,
    TournamentParticipant,
    TournamentStatus,
)
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
                id=3,
                order_number="10000003",
                telegram_id=42,
                product_id=12,
                product_title="300 Coin",
                product_type="COIN",
                coins_amount=300,
                price_uzs=Decimal("22000"),
                locked_price=Decimal("22000"),
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


def test_completed_300_coin_order_also_registers_open_purchase_tournament(sessions):
    now = datetime.now(timezone.utc)
    with sessions() as db:
        tournament = Tournament(
            name="Purchase Cup",
            format=TournamentFormat.GROUP_PLAYOFF,
            status=TournamentStatus.REGISTRATION,
            max_participants=4,
            ticket_cost=2,
            entry_mode=TournamentEntryMode.COIN_PURCHASE,
            minimum_coin_purchase=300,
            duration_days=5,
            auto_start_when_full=True,
            group_count=1,
            group_size=4,
            group_mode=TournamentGroupMode.POINTS,
            qualifiers_per_group=2,
            registration_opens_at=now - timedelta(hours=1),
            registration_closes_at=now + timedelta(days=2),
            created_by=700,
        )
        db.add(tournament)
        db.commit()
        completed = approve_order(db, 3, 700)

        assert completed._ticket_bonus_awarded == 30
        assert completed._tournament_registration_ids == [tournament.id]
        participant = db.query(TournamentParticipant).one()
        assert participant.telegram_id == 42
        assert participant.qualification_order_id == 3
        assert participant.qualification_coin_amount == 300
        assert db.get(GameTicketWallet, 42).tournament_tickets == 30
