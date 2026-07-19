from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crud.coin_credentials import cleanup_sensitive_order_data
from app.models.wheel import WheelCoinOrder
from app.models.wheel_coin_order_audit import WheelCoinOrderAudit


ACTIVE_WHEEL_COIN_ORDER_STATUSES = frozenset({
    "WAITING_DETAILS",
    "WAITING_OPERATOR",
    "WAITING_OTP",
    "OTP_SUBMITTED",
    "PENDING",
    "CLAIMED",
})


def list_wheel_coin_orders(db: Session) -> list[WheelCoinOrder]:
    return (
        db.query(WheelCoinOrder)
        .order_by(WheelCoinOrder.created_at.desc(), WheelCoinOrder.id.desc())
        .all()
    )


def cancel_wheel_coin_order(
    db: Session,
    order_id: int,
    admin_telegram_id: int,
) -> WheelCoinOrder | None | str:
    try:
        order = (
            db.query(WheelCoinOrder)
            .filter(WheelCoinOrder.id == order_id)
            .with_for_update()
            .first()
        )
        if order is None:
            return None
        if order.status not in ACTIVE_WHEEL_COIN_ORDER_STATUSES:
            return "not_cancellable"

        old_status = order.status
        cleanup_sensitive_order_data(db, "WHEEL", order.id)
        order.konami_login = None
        order.konami_password = None
        order.status = "CANCELLED"
        order.updated_at = datetime.now(timezone.utc)
        db.add(WheelCoinOrderAudit(
            admin_telegram_id=admin_telegram_id,
            order_id=order.id,
            old_status=old_status,
            new_status="CANCELLED",
            reason="Admin cleanup",
        ))
        db.commit()
        db.refresh(order)
        return order
    except Exception:
        db.rollback()
        raise
