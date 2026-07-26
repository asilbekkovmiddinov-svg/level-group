from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.campaign import Campaign, CampaignRecipient
from app.models.p2p import P2POrder, P2PTrade
from app.models.promotion import Promotion
from app.models.user import User
from app.models.wallet import Wallet
from app.routers.p2p import create_trade, enqueue_trade_notification
from app.schemas.p2p import P2PTradeCreate


TABLES = [
    User.__table__, Wallet.__table__, Promotion.__table__,
    P2POrder.__table__, P2PTrade.__table__,
    Campaign.__table__, CampaignRecipient.__table__,
]


def sessions():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=TABLES)
    return sessionmaker(bind=engine, expire_on_commit=False)


def seed(session_factory):
    db = session_factory()
    db.add_all([
        User(telegram_id=101, first_name="Seller", is_banned=False),
        User(telegram_id=202, first_name="Buyer", is_banned=False),
        Wallet(telegram_id=101, efc_balance=Decimal("0"), uzs_balance=Decimal("0"), locked_efc=Decimal("100"), locked_uzs=Decimal("0")),
        Wallet(telegram_id=202, efc_balance=Decimal("0"), uzs_balance=Decimal("100000"), locked_efc=Decimal("0"), locked_uzs=Decimal("0")),
    ])
    order = P2POrder(
        owner_id=101, order_type="SELL", efc_amount=Decimal("100"),
        remaining_efc=Decimal("100"), price_uzs=Decimal("100"),
        min_trade_efc=Decimal("50"), response_minutes=15,
        locked_currency="EFC", locked_amount=Decimal("100"), status="OPEN",
    )
    db.add(order)
    db.commit()
    order_id = order.id
    db.close()
    return order_id


def test_trade_and_seller_recipient_are_committed_together():
    session_factory = sessions()
    order_id = seed(session_factory)
    db = session_factory()

    result = create_trade(
        order_id, P2PTradeCreate(telegram_id=202, efc_amount=50), db,
    )

    assert result["success"] is True
    trade = db.query(P2PTrade).one()
    campaign = db.query(Campaign).one()
    recipient = db.query(CampaignRecipient).one()
    assert campaign.event_type == "P2P_TRADE_CREATED"
    assert campaign.event_key == f"p2p_trade_created:{trade.id}:seller"
    assert campaign.status == "RUNNING"
    assert campaign.button_target == str(trade.id)
    assert recipient.user_id == trade.owner_id == 101
    assert recipient.status == "PENDING"
    db.close()


def test_trade_notification_is_idempotent_per_trade():
    session_factory = sessions()
    order_id = seed(session_factory)
    db = session_factory()
    create_trade(order_id, P2PTradeCreate(telegram_id=202, efc_amount=50), db)
    trade = db.query(P2PTrade).one()

    first = enqueue_trade_notification(db, trade)
    second = enqueue_trade_notification(db, trade)
    db.commit()

    assert first.id == second.id
    assert db.query(Campaign).count() == 1
    assert db.query(CampaignRecipient).count() == 1
    db.close()


def test_notification_commit_failure_rolls_back_trade_and_wallet_lock():
    session_factory = sessions()
    order_id = seed(session_factory)
    db = session_factory()
    original_commit = db.commit

    def fail_commit():
        raise RuntimeError("database unavailable")

    db.commit = fail_commit
    with pytest.raises(RuntimeError, match="database unavailable"):
        create_trade(order_id, P2PTradeCreate(telegram_id=202, efc_amount=50), db)
    db.rollback()
    db.commit = original_commit
    db.close()

    verify = session_factory()
    wallet = verify.query(Wallet).filter(Wallet.telegram_id == 202).one()
    assert verify.query(P2PTrade).count() == 0
    assert verify.query(Campaign).count() == 0
    assert verify.query(CampaignRecipient).count() == 0
    assert wallet.uzs_balance == Decimal("100000")
    assert wallet.locked_uzs == Decimal("0")
    verify.close()
