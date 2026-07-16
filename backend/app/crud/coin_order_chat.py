from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.coin_order_message import CoinOrderMessage
from app.models.order import Order
from app.models.wheel import WheelCoinOrder

ORDER_MODELS = {"SHOP": Order, "WHEEL": WheelCoinOrder}
ACTIVE_STATUSES = {"WAITING_DETAILS", "WAITING_OTP", "OTP_SUBMITTED", "PENDING", "CLAIMED"}


def normalize_order_type(value: str) -> str | None:
    value = str(value or "").upper()
    return value if value in ORDER_MODELS else None


def get_coin_order(db: Session, order_type: str, order_id: int):
    model = ORDER_MODELS.get(normalize_order_type(order_type))
    return db.query(model).filter(model.id == order_id).first() if model else None


def list_messages(db: Session, order_type: str, order_id: int):
    return db.query(CoinOrderMessage).filter(
        CoinOrderMessage.order_type == normalize_order_type(order_type),
        CoinOrderMessage.order_id == order_id,
    ).order_by(CoinOrderMessage.id.asc()).all()


def add_message(db: Session, order_type: str, order, sender: str, sender_id: int, message: str):
    item = CoinOrderMessage(
        order_type=normalize_order_type(order_type), order_id=order.id,
        telegram_id=order.telegram_id, sender=sender, sender_id=sender_id,
        message=message.strip(),
    )
    db.add(item)
    if sender == "USER" and order.status == "WAITING_OTP" and message.strip().isdigit() and len(message.strip()) == 6:
        order.status = "OTP_SUBMITTED"
    db.commit(); db.refresh(item); db.refresh(order)
    return item


def mark_read(db: Session, order_type: str, order_id: int, reader: str):
    sender = "OPERATOR" if reader == "USER" else "USER"
    count = db.query(CoinOrderMessage).filter(
        CoinOrderMessage.order_type == normalize_order_type(order_type),
        CoinOrderMessage.order_id == order_id,
        CoinOrderMessage.sender == sender,
        CoinOrderMessage.read_at.is_(None),
    ).update({CoinOrderMessage.read_at: datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit(); return count


def unread_count(db: Session, order_type: str, order_id: int, reader: str):
    sender = "OPERATOR" if reader == "USER" else "USER"
    return db.query(CoinOrderMessage).filter(
        CoinOrderMessage.order_type == normalize_order_type(order_type),
        CoinOrderMessage.order_id == order_id,
        CoinOrderMessage.sender == sender,
        CoinOrderMessage.read_at.is_(None),
    ).count()


def active_orders(db: Session):
    result = []
    for order_type, model in ORDER_MODELS.items():
        for order in db.query(model).filter(model.status.in_(ACTIVE_STATUSES)).order_by(model.id.asc()).all():
            result.append((order_type, order, unread_count(db, order_type, order.id, "OPERATOR")))
    return result


def apply_operator_action(order, action: str, admin_id: int):
    action = action.upper()
    if action in {"REQUEST_CODE", "WRONG_CODE", "RESEND_CODE"}:
        if order.status not in {"WAITING_DETAILS", "WAITING_OTP", "OTP_SUBMITTED"}:
            return False
        order.status = "WAITING_OTP"
        return True
    if action == "ACCEPT_CODE" and order.status == "OTP_SUBMITTED":
        order.status = "PENDING"
        return True
    return False
