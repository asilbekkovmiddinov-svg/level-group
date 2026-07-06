from datetime import datetime
from decimal import Decimal, ROUND_DOWN

from sqlalchemy.orm import Session

from app.models.p2p import P2POrder, P2PTrade
from app.crud.wallet import (
    lock_efc_balance,
    unlock_efc_balance,
    confirm_locked_efc,
    lock_uzs_balance,
    unlock_uzs_balance,
    confirm_locked_uzs,
    add_efc_balance,
    add_uzs_balance,
)
from app.crud.transaction import create_transaction

P2P_FEE_PERCENT = Decimal("0.025")

MIN_EFC_AMOUNT = Decimal("50")
MAX_EFC_AMOUNT = Decimal("10000")

ORDER_TYPE_BUY = "BUY"
ORDER_TYPE_SELL = "SELL"

ORDER_STATUS_OPEN = "OPEN"
ORDER_STATUS_PARTIAL = "PARTIAL"
ORDER_STATUS_COMPLETED = "COMPLETED"
ORDER_STATUS_CANCELLED = "CANCELLED"

TRADE_STATUS_PENDING = "PENDING"
TRADE_STATUS_OWNER_APPROVED = "OWNER_APPROVED"
TRADE_STATUS_COMPLETED = "COMPLETED"
TRADE_STATUS_REJECTED = "REJECTED"


def to_decimal(value):
    return Decimal(str(value))


def round_efc(value):
    return to_decimal(value).quantize(
        Decimal("0.0001"),
        rounding=ROUND_DOWN,
    )


def round_uzs(value):
    return to_decimal(value).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )


def calculate_total_uzs(efc_amount, price_uzs):
    return round_uzs(round_efc(efc_amount) * round_uzs(price_uzs))


def calculate_efc_fee(efc_amount):
    return round_efc(round_efc(efc_amount) * P2P_FEE_PERCENT)


def calculate_uzs_fee(total_uzs):
    return round_uzs(round_uzs(total_uzs) * P2P_FEE_PERCENT)


def get_p2p_order(db: Session, order_id: int):
    return db.query(P2POrder).filter(
        P2POrder.id == order_id
    ).first()


def get_p2p_trade(db: Session, trade_id: int):
    return db.query(P2PTrade).filter(
        P2PTrade.id == trade_id
    ).first()


def get_open_p2p_orders(db: Session, order_type: str | None = None):
    query = db.query(P2POrder).filter(
        P2POrder.status.in_([ORDER_STATUS_OPEN, ORDER_STATUS_PARTIAL])
    )

    if order_type:
        query = query.filter(P2POrder.order_type == order_type.upper())

    if order_type == ORDER_TYPE_BUY:
        query = query.order_by(P2POrder.price_uzs.desc())
    elif order_type == ORDER_TYPE_SELL:
        query = query.order_by(P2POrder.price_uzs.asc())
    else:
        query = query.order_by(P2POrder.id.desc())

    return query.all()


def get_my_p2p_orders(db: Session, telegram_id: int):
    return db.query(P2POrder).filter(
        P2POrder.owner_id == telegram_id
    ).order_by(
        P2POrder.id.desc()
    ).all()


def get_my_p2p_trades(db: Session, telegram_id: int):
    return db.query(P2PTrade).filter(
        (P2PTrade.owner_id == telegram_id)
        | (P2PTrade.requester_id == telegram_id)
    ).order_by(
        P2PTrade.id.desc()
    ).all()
def create_p2p_order(
    db: Session,
    telegram_id: int,
    order_type: str,
    efc_amount,
    price_uzs,
    min_trade_efc,
    response_minutes,
):
    order_type = order_type.upper()
    efc_amount = round_efc(efc_amount)
    price_uzs = round_uzs(price_uzs)
    min_trade_efc = round_efc(min_trade_efc)

    if order_type not in [ORDER_TYPE_BUY, ORDER_TYPE_SELL]:
        return "invalid_order_type"

    if efc_amount < MIN_EFC_AMOUNT:
        return "min_efc"

    if efc_amount > MAX_EFC_AMOUNT:
        return "max_efc"

    if min_trade_efc < MIN_EFC_AMOUNT:
        return "min_trade"

    if min_trade_efc > efc_amount:
        return "min_trade"

    total_uzs = calculate_total_uzs(efc_amount, price_uzs)

    if order_type == ORDER_TYPE_SELL:
        locked = lock_efc_balance(
            db=db,
            telegram_id=telegram_id,
            amount=efc_amount,
        )

        if not locked:
            return "insufficient_efc"

        locked_currency = "EFC"
        locked_amount = efc_amount

    else:
        locked = lock_uzs_balance(
            db=db,
            telegram_id=telegram_id,
            amount=total_uzs,
        )

        if not locked:
            return "insufficient_uzs"

        locked_currency = "UZS"
        locked_amount = total_uzs

    order = P2POrder(
        owner_id=telegram_id,
        order_type=order_type,
        efc_amount=efc_amount,
        remaining_efc=efc_amount,
        price_uzs=price_uzs,
        min_trade_efc=min_trade_efc,
        response_minutes=response_minutes,
        locked_currency=locked_currency,
        locked_amount=locked_amount,
        status=ORDER_STATUS_OPEN,
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    create_transaction(
        db=db,
        telegram_id=telegram_id,
        currency=locked_currency,
        amount=locked_amount,
        balance_before=0,
        balance_after=0,
        type="P2P_CREATE",
        description=f"P2P {order_type} e’lon yaratildi. Order #{order.id}",
    )

    return order


def create_p2p_trade(
    db: Session,
    order_id: int,
    telegram_id: int,
    efc_amount,
):
    order = get_p2p_order(db, order_id)

    if not order:
        return None

    if order.status not in [ORDER_STATUS_OPEN, ORDER_STATUS_PARTIAL]:
        return "not_open"

    if order.owner_id == telegram_id:
        return "own_order"

    efc_amount = round_efc(efc_amount)

    if efc_amount < order.min_trade_efc:
        return "min_trade"

    if efc_amount > order.remaining_efc:
        return "too_much"

    total_uzs = calculate_total_uzs(efc_amount, order.price_uzs)
    efc_fee = calculate_efc_fee(efc_amount)
    uzs_fee = calculate_uzs_fee(total_uzs)

    if order.order_type == ORDER_TYPE_SELL:
        locked = lock_uzs_balance(
            db=db,
            telegram_id=telegram_id,
            amount=total_uzs + uzs_fee,
        )

        if not locked:
            return "insufficient_uzs"

    else:
        locked = lock_efc_balance(
            db=db,
            telegram_id=telegram_id,
            amount=efc_amount + efc_fee,
        )

        if not locked:
            return "insufficient_efc"

    trade = P2PTrade(
        order_id=order.id,
        owner_id=order.owner_id,
        requester_id=telegram_id,
        order_type=order.order_type,
        efc_amount=efc_amount,
        price_uzs=order.price_uzs,
        total_uzs=total_uzs,
        efc_fee=efc_fee,
        uzs_fee=uzs_fee,
        owner_status="PENDING",
        requester_status="PENDING",
        status=TRADE_STATUS_PENDING,
    )

    db.add(trade)
    db.commit()
    db.refresh(trade)

    return trade


def approve_p2p_trade(
    db: Session,
    trade_id: int,
    telegram_id: int,
):
    trade = get_p2p_trade(db, trade_id)

    if not trade:
        return None

    if trade.owner_id != telegram_id:
        return "not_owner"

    if trade.status != TRADE_STATUS_PENDING:
        return "not_pending"

    trade.owner_status = "APPROVED"
    trade.status = TRADE_STATUS_OWNER_APPROVED
    trade.approved_at = datetime.utcnow()

    db.commit()
    db.refresh(trade)

    return trade
def reject_p2p_trade(
    db: Session,
    trade_id: int,
    telegram_id: int,
):
    trade = get_p2p_trade(db, trade_id)

    if not trade:
        return None

    if trade.owner_id != telegram_id:
        return "not_owner"

    if trade.status != TRADE_STATUS_PENDING:
        return "not_pending"

    if trade.order_type == ORDER_TYPE_SELL:
        unlock_uzs_balance(
            db=db,
            telegram_id=trade.requester_id,
            amount=trade.total_uzs + trade.uzs_fee,
        )
    else:
        unlock_efc_balance(
            db=db,
            telegram_id=trade.requester_id,
            amount=trade.efc_amount + trade.efc_fee,
        )

    trade.owner_status = "REJECTED"
    trade.status = TRADE_STATUS_REJECTED
    trade.rejected_at = datetime.utcnow()

    db.commit()
    db.refresh(trade)

    create_transaction(
        db=db,
        telegram_id=trade.requester_id,
        currency="P2P",
        amount=0,
        balance_before=0,
        balance_after=0,
        type="P2P_REJECT",
        description=f"P2P trade #{trade.id} rad etildi.",
    )

    return trade


def confirm_p2p_trade(
    db: Session,
    trade_id: int,
    telegram_id: int,
):
    trade = get_p2p_trade(db, trade_id)

    if not trade:
        return None

    if trade.requester_id != telegram_id:
        return "not_requester"

    if trade.status != TRADE_STATUS_OWNER_APPROVED:
        return "not_approved"

    order = get_p2p_order(db, trade.order_id)

    if not order:
        return None

    if trade.efc_amount > order.remaining_efc:
        return "too_much"

    if trade.order_type == ORDER_TYPE_SELL:
        confirm_locked_uzs(
            db=db,
            telegram_id=trade.requester_id,
            amount=trade.total_uzs + trade.uzs_fee,
        )

        confirm_locked_efc(
            db=db,
            telegram_id=trade.owner_id,
            amount=trade.efc_amount,
        )

        add_efc_balance(
            db=db,
            telegram_id=trade.requester_id,
            amount=trade.efc_amount - trade.efc_fee,
        )

        add_uzs_balance(
            db=db,
            telegram_id=trade.owner_id,
            amount=trade.total_uzs,
        )

    else:
        confirm_locked_efc(
            db=db,
            telegram_id=trade.requester_id,
            amount=trade.efc_amount + trade.efc_fee,
        )

        confirm_locked_uzs(
            db=db,
            telegram_id=trade.owner_id,
            amount=trade.total_uzs,
        )

        add_efc_balance(
            db=db,
            telegram_id=trade.owner_id,
            amount=trade.efc_amount,
        )

        add_uzs_balance(
            db=db,
            telegram_id=trade.requester_id,
            amount=trade.total_uzs - trade.uzs_fee,
        )

    order.remaining_efc = round_efc(order.remaining_efc - trade.efc_amount)

    if order.remaining_efc <= 0:
        order.status = ORDER_STATUS_COMPLETED
        order.completed_at = datetime.utcnow()
    else:
        order.status = ORDER_STATUS_PARTIAL

    trade.requester_status = "CONFIRMED"
    trade.status = TRADE_STATUS_COMPLETED
    trade.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(trade)

    create_transaction(
        db=db,
        telegram_id=trade.owner_id,
        currency="P2P",
        amount=trade.efc_amount,
        balance_before=0,
        balance_after=0,
        type="P2P_OWNER_COMPLETE",
        description=f"P2P trade #{trade.id} yakunlandi.",
    )

    create_transaction(
        db=db,
        telegram_id=trade.requester_id,
        currency="P2P",
        amount=trade.efc_amount,
        balance_before=0,
        balance_after=0,
        type="P2P_REQUESTER_COMPLETE",
        description=f"P2P trade #{trade.id} yakunlandi.",
    )

    return trade


def cancel_p2p_order(
    db: Session,
    order_id: int,
    telegram_id: int,
):
    order = get_p2p_order(db, order_id)

    if not order:
        return None

    if order.owner_id != telegram_id:
        return "not_owner"

    if order.status not in [ORDER_STATUS_OPEN, ORDER_STATUS_PARTIAL]:
        return "cannot_cancel"

    if order.order_type == ORDER_TYPE_SELL:
        unlock_efc_balance(
            db=db,
            telegram_id=telegram_id,
            amount=order.remaining_efc,
        )
    else:
        remaining_uzs = calculate_total_uzs(
            order.remaining_efc,
            order.price_uzs,
        )

        unlock_uzs_balance(
            db=db,
            telegram_id=telegram_id,
            amount=remaining_uzs,
        )

    order.status = ORDER_STATUS_CANCELLED
    order.cancelled_at = datetime.utcnow()

    db.commit()
    db.refresh(order)

    create_transaction(
        db=db,
        telegram_id=telegram_id,
        currency="P2P",
        amount=order.remaining_efc,
        balance_before=0,
        balance_after=0,
        type="P2P_CANCEL",
        description=f"P2P order #{order.id} bekor qilindi.",
    )

    return order
    
def update_p2p_order_price(
    db: Session,
    order_id: int,
    telegram_id: int,
    price_uzs,
):
    order = get_p2p_order(db, order_id)

    if not order:
        return None

    if order.owner_id != telegram_id:
        return "not_owner"

    if order.status not in [ORDER_STATUS_OPEN, ORDER_STATUS_PARTIAL]:
        return "cannot_update"

    price_uzs = round_uzs(price_uzs)

    if price_uzs <= 0:
        return "invalid_price"

    pending_trade = db.query(P2PTrade).filter(
        P2PTrade.order_id == order_id,
        P2PTrade.status.in_([
            TRADE_STATUS_PENDING,
            TRADE_STATUS_OWNER_APPROVED,
        ]),
    ).first()

    if pending_trade:
        return "has_pending_trade"

    order.price_uzs = price_uzs

    db.commit()
    db.refresh(order)

    create_transaction(
        db=db,
        telegram_id=telegram_id,
        currency="P2P",
        amount=0,
        balance_before=0,
        balance_after=0,
        type="P2P_UPDATE_PRICE",
        description=f"P2P order #{order.id} narxi yangilandi.",
    )

    return order
