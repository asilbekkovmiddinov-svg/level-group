from datetime import datetime
from decimal import Decimal, ROUND_DOWN

from sqlalchemy.orm import Session

from app.models.p2p import P2POrder
from app.crud.wallet import (
    lock_efc_balance,
    unlock_efc_balance,
    confirm_locked_efc,
    add_efc_balance,
    subtract_uzs_balance,
    add_uzs_balance,
)
from app.crud.transaction import create_transaction

P2P_FEE_PERCENT = Decimal("0.025")


def to_decimal(amount):
    return Decimal(str(amount))


def round_uzs(amount):
    return to_decimal(amount).quantize(Decimal("0.01"))


def round_efc(amount):
    return to_decimal(amount).quantize(
        Decimal("0.0001"),
        rounding=ROUND_DOWN,
    )


def calculate_fees(efc_amount, price_uzs):
    efc_amount = round_efc(efc_amount)
    price_uzs = round_uzs(price_uzs)

    seller_fee_efc = round_efc(efc_amount * P2P_FEE_PERCENT)
    buyer_fee_uzs = round_uzs(price_uzs * P2P_FEE_PERCENT)

    return {
        "seller_fee_efc": seller_fee_efc,
        "buyer_fee_uzs": buyer_fee_uzs,
        "buyer_receive_efc": round_efc(efc_amount - seller_fee_efc),
        "total_buyer_pay_uzs": round_uzs(price_uzs + buyer_fee_uzs),
        "seller_receive_uzs": price_uzs,
    }


def create_p2p_order(db: Session, telegram_id: int, efc_amount, price_uzs):
    efc_amount = round_efc(efc_amount)
    price_uzs = round_uzs(price_uzs)

    fees = calculate_fees(efc_amount, price_uzs)

    locked = lock_efc_balance(
        db=db,
        telegram_id=telegram_id,
        amount=efc_amount,
    )

    if not locked:
        return "insufficient_efc"

    order = P2POrder(
        seller_id=telegram_id,
        efc_amount=efc_amount,
        price_uzs=price_uzs,
        seller_fee_efc=fees["seller_fee_efc"],
        buyer_fee_uzs=fees["buyer_fee_uzs"],
        total_buyer_pay_uzs=fees["total_buyer_pay_uzs"],
        seller_receive_uzs=fees["seller_receive_uzs"],
        status="OPEN",
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    create_transaction(
        db=db,
        telegram_id=telegram_id,
        currency="EFC",
        amount=efc_amount,
        balance_before=locked.efc_balance + efc_amount,
        balance_after=locked.efc_balance,
        type="P2P_CREATE",
        description=f"P2P e'lon yaratildi. Order #{order.id}",
    )

    return order


def get_open_p2p_orders(db: Session):
    return db.query(P2POrder).filter(
        P2POrder.status == "OPEN"
    ).order_by(
        P2POrder.id.desc()
    ).all()


def get_p2p_order(db: Session, order_id: int):
    return db.query(P2POrder).filter(
        P2POrder.id == order_id
    ).first()
def reserve_p2p_order(db: Session, order_id: int, buyer_id: int):
    order = get_p2p_order(db, order_id)

    if not order:
        return None

    if order.status != "OPEN":
        return "not_open"

    if order.seller_id == buyer_id:
        return "own_order"

    order.buyer_id = buyer_id
    order.status = "RESERVED"
    order.reserved_at = datetime.utcnow()

    db.commit()
    db.refresh(order)

    return order


def complete_p2p_order(db: Session, order_id: int, buyer_id: int):
    order = get_p2p_order(db, order_id)

    if not order:
        return None

    if order.status != "RESERVED":
        return "not_reserved"

    if order.buyer_id != buyer_id:
        return "not_buyer"

    buyer_payment = to_decimal(order.total_buyer_pay_uzs)
    seller_receive = to_decimal(order.seller_receive_uzs)
    buyer_receive_efc = round_efc(
        to_decimal(order.efc_amount) - to_decimal(order.seller_fee_efc)
    )

    buyer_wallet = subtract_uzs_balance(
        db=db,
        telegram_id=buyer_id,
        amount=buyer_payment,
    )

    if not buyer_wallet:
        return "insufficient_uzs"

    seller_wallet = add_uzs_balance(
        db=db,
        telegram_id=order.seller_id,
        amount=seller_receive,
    )

    confirm_locked_efc(
        db=db,
        telegram_id=order.seller_id,
        amount=order.efc_amount,
    )

    buyer_efc_wallet = add_efc_balance(
        db=db,
        telegram_id=buyer_id,
        amount=buyer_receive_efc,
    )

    order.status = "COMPLETED"
    order.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(order)

    create_transaction(
        db=db,
        telegram_id=buyer_id,
        currency="UZS",
        amount=buyer_payment,
        balance_before=buyer_wallet.uzs_balance + buyer_payment,
        balance_after=buyer_wallet.uzs_balance,
        type="P2P_BUY",
        description=f"P2P order #{order.id} sotib olindi.",
    )

    create_transaction(
        db=db,
        telegram_id=order.seller_id,
        currency="UZS",
        amount=seller_receive,
        balance_before=seller_wallet.uzs_balance - seller_receive,
        balance_after=seller_wallet.uzs_balance,
        type="P2P_SELL",
        description=f"P2P order #{order.id} sotildi.",
    )

    create_transaction(
        db=db,
        telegram_id=buyer_id,
        currency="EFC",
        amount=buyer_receive_efc,
        balance_before=buyer_efc_wallet.efc_balance - buyer_receive_efc,
        balance_after=buyer_efc_wallet.efc_balance,
        type="P2P_RECEIVE_EFC",
        description=f"P2P order #{order.id}. Seller fee EFC burn qilindi.",
    )

    return order


def cancel_p2p_order(db: Session, order_id: int, telegram_id: int):
    order = get_p2p_order(db, order_id)

    if not order:
        return None

    if order.seller_id != telegram_id:
        return "not_seller"

    if order.status not in ["OPEN", "RESERVED"]:
        return "cannot_cancel"

    unlock_efc_balance(
        db=db,
        telegram_id=telegram_id,
        amount=order.efc_amount,
    )

    order.status = "CANCELLED"
    order.cancelled_at = datetime.utcnow()

    db.commit()
    db.refresh(order)

    return order
