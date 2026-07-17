from sqlalchemy.orm import Session

from app.crud.coin_order_chat import ORDER_CREATED_MESSAGE, normalize_order_type
from app.models.coin_order_message import CoinOrderMessage


def begin_operator_wait(db: Session, order_type: str, order):
    kind = normalize_order_type(order_type)
    if not kind:
        raise ValueError("Unsupported Coin order type")
    order.status = "WAITING_OPERATOR"
    exists = db.query(CoinOrderMessage.id).filter_by(
        order_type=kind, order_id=order.id, sender="SYSTEM", message=ORDER_CREATED_MESSAGE,
    ).first()
    if not exists:
        db.add(CoinOrderMessage(order_type=kind, order_id=order.id, telegram_id=order.telegram_id,
            sender="SYSTEM", sender_id=None, message=ORDER_CREATED_MESSAGE))
    db.commit()
    db.refresh(order)
    return order
