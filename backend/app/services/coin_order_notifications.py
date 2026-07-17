from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.user import User
from app.models.wheel import WheelCoinOrder
from app.services.telegram_notifications import send_admin_message

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoinOrderNotificationResult:
    status: str
    sent: bool


def _model(order_type: str):
    return {"SHOP": Order, "WHEEL": WheelCoinOrder}.get(order_type.upper())


def _snapshot(order_type: str, order, user):
    return {
        "id": order.id,
        "type": order_type,
        "coins": order.coins_amount if order_type == "SHOP" else order.coin_amount,
        "platform": order.platform if order_type == "SHOP" else order.device,
        "region": order.region,
        "status": order.status,
        "telegram_id": order.telegram_id,
        "username": (user.username if user else None) or getattr(order, "username", None),
        "created_at": order.created_at,
    }


def _text(value):
    username = f"@{value['username'].lstrip('@')}" if value["username"] else "—"
    created_at = value["created_at"] or datetime.now(timezone.utc)
    return "\n".join((
        "🪙 Yangi Coin buyurtma",
        "",
        f"🆔 Order ID: #{value['id']}",
        f"📦 Manba: {value['type']}",
        f"🪙 Coin: {value['coins']}",
        f"📱 Platforma: {value['platform'] or '—'}",
        f"🌍 Region: {value['region'] or '—'}",
        f"📌 Status: {value['status']}",
        f"👤 Telegram ID: {value['telegram_id']}",
        f"🔗 Username: {username}",
        f"🕒 Sana: {created_at}",
    ))


def send_coin_order_notification(db: Session, order_type: str, order_id: int):
    kind = order_type.upper()
    model = _model(kind)
    if not model:
        return CoinOrderNotificationResult("SKIPPED", False)

    order = db.query(model).filter(model.id == order_id).with_for_update().first()
    if not order or order.status != "WAITING_OPERATOR":
        db.rollback()
        return CoinOrderNotificationResult("SKIPPED", False)
    if order.coin_notification_status in {"SENDING", "SENT"}:
        status = order.coin_notification_status
        db.rollback()
        return CoinOrderNotificationResult(status, False)

    user = db.query(User).filter(User.telegram_id == order.telegram_id).first()
    snapshot = _snapshot(kind, order, user)
    order.coin_notification_status = "SENDING"
    order.coin_notification_attempts = (order.coin_notification_attempts or 0) + 1
    order.coin_notification_last_error = None
    db.commit()

    try:
        telegram = send_admin_message(
            _text(snapshot),
            reply_markup={"inline_keyboard": [[{
                "text": "💬 Buyurtmani ochish",
                "callback_data": f"coinchatopen:{kind}:{order_id}",
            }]]},
        )
    except Exception as error:
        failed = db.query(model).filter(model.id == order_id).with_for_update().first()
        if failed and failed.coin_notification_status == "SENDING":
            failed.coin_notification_status = "FAILED"
            failed.coin_notification_last_error = type(error).__name__[:255]
            db.commit()
        logger.exception("Coin order admin notification failed", extra={"order_type": kind, "order_id": order_id})
        return CoinOrderNotificationResult("FAILED", False)

    sent = db.query(model).filter(model.id == order_id).with_for_update().first()
    if sent and sent.coin_notification_status == "SENDING":
        sent.coin_notification_status = "SENT"
        sent.coin_notification_message_id = str(telegram.message_id)
        sent.coin_notification_sent_at = datetime.now(timezone.utc)
        sent.coin_notification_last_error = None
        db.commit()
    return CoinOrderNotificationResult("SENT", True)
