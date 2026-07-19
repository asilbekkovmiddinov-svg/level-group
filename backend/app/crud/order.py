from decimal import Decimal
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import logging
import secrets
import threading

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.product import Product
from app.schemas.order import OrderCreate
from app.crud.wallet import get_wallet_for_update, add_uzs
from app.crud.transaction import create_transaction
from app.services.referrals import award_first_shop_bonus
from app.services.coin_promotions import confirm_locked, release_locked, reserve
from app.core.config import COIN_PROMOTION_ORDER_TIMEOUT_SECONDS


logger = logging.getLogger(__name__)
_promotion_order_locks: dict[int, threading.Lock] = {}
_promotion_order_locks_guard = threading.Lock()


def _promotion_order_lock(product_id: int) -> threading.Lock:
    with _promotion_order_locks_guard:
        return _promotion_order_locks.setdefault(product_id, threading.Lock())


def _new_order_number(db: Session) -> str:
    for _ in range(32):
        value = str(secrets.randbelow(90_000_000) + 10_000_000)
        if not db.query(Order.id).filter(Order.order_number == value).first():
            return value
    raise RuntimeError("Unique order number could not be generated")


def _order_fingerprint(product_id, platform, region):
    return sha256(
        f"SHOP:{product_id}:{platform}:{region}".encode()
    ).hexdigest()


def _sqlalchemy_error_diagnostics(error: SQLAlchemyError) -> dict[str, str | None]:
    """Return driver metadata without logging SQL parameters or request payloads."""
    original = getattr(error, "orig", None)
    diagnostic = getattr(original, "diag", None)
    return {
        "exception_type": type(error).__name__,
        "driver_exception_type": type(original).__name__ if original else None,
        "exception_message": str(original) if original else type(error).__name__,
        "postgresql_error_code": (
            getattr(original, "sqlstate", None)
            or getattr(original, "pgcode", None)
        ),
        "constraint": getattr(diagnostic, "constraint_name", None),
        "table": getattr(diagnostic, "table_name", None),
        "column": getattr(diagnostic, "column_name", None),
    }


def create_order(
    db: Session,
    data: OrderCreate,
    telegram_id: int,
    idempotency_key: str | None = None,
):
    lock = _promotion_order_lock(data.product_id)
    lock.acquire()
    try:
        with db.begin():
            if idempotency_key:
                replay = db.query(Order).filter(
                    Order.telegram_id == telegram_id,
                    Order.idempotency_key == idempotency_key,
                ).first()
                if replay:
                    platform = str(data.platform or replay.platform or "ANDROID").strip().upper()
                    region = str(data.region or replay.region or "GLOBAL").strip().upper()
                    fingerprint = _order_fingerprint(data.product_id, platform, region)
                    replay._idempotency_replay = True
                    return replay if replay.request_fingerprint == fingerprint else "idempotency_conflict"

            product = db.query(Product).filter(
                Product.id == data.product_id,
                Product.is_active == True,
            ).first()
            if not product:
                return "product_not_found"

            promotion, promotion_error = reserve(db, product.id, telegram_id)
            if promotion_error == "user_limit":
                return "promotion_user_limit"

            raw_platform = data.platform or product.platform or "ANDROID"
            platform = str(raw_platform).strip().upper()
            if platform not in {"ANDROID", "IOS"}:
                platform = "ANDROID" if product.category == "ANDROID_COINS" else "IOS"
            region = str(data.region or product.region or "GLOBAL").strip().upper()
            if not region or len(region) > 100:
                return "invalid_details"
            fingerprint = _order_fingerprint(data.product_id, platform, region)

            wallet = get_wallet_for_update(db, telegram_id)
            if not wallet:
                return "wallet_not_found"

            price = Decimal(str(promotion.promotion_price if promotion else product.price_uzs))
            balance_before = Decimal(str(wallet.uzs_balance))
            if balance_before < price:
                return "insufficient_balance"
            wallet.uzs_balance = balance_before - price

            order = Order(
                order_number=_new_order_number(db),
                telegram_id=telegram_id,
                product_id=product.id,
                product_title=product.title,
                coins_amount=product.coins_amount,
                price_uzs=price,
                locked_price=price,
                promotion_id=promotion.id if promotion else None,
                region=region,
                platform=platform,
                status="WAITING_OPERATOR",
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                expires_at=(
                    datetime.now(timezone.utc) + timedelta(seconds=COIN_PROMOTION_ORDER_TIMEOUT_SECONDS)
                    if promotion else None
                ),
            )
            db.add(order)
            db.flush()
            create_transaction(
                db=db,
                telegram_id=telegram_id,
                currency="UZS",
                amount=price,
                balance_before=balance_before,
                balance_after=wallet.uzs_balance,
                type="ORDER_PAYMENT",
                description=f"Order payment for {product.title}",
                commit=False,
            )
            order._idempotency_replay = False
            return order
    except SQLAlchemyError as error:
        details = _sqlalchemy_error_diagnostics(error)
        logger.exception(
            "Coin Shop order transaction failed: "
            "exception_type=%s driver_exception_type=%s exception_message=%s "
            "postgresql_error_code=%s constraint=%s table=%s column=%s",
            details["exception_type"],
            details["driver_exception_type"],
            details["exception_message"],
            details["postgresql_error_code"],
            details["constraint"],
            details["table"],
            details["column"],
        )
        return "operation_failed"
    finally:
        lock.release()


def get_user_orders(db: Session, telegram_id: int):
    return (
        db.query(Order)
        .filter(Order.telegram_id == telegram_id)
        .order_by(Order.id.desc())
        .all()
    )


def claim_order(db: Session, order_id: int, admin_id: int):
    order = db.query(Order).filter(
        Order.id == order_id
    ).first()

    if not order:
        return None

    if order.status == "CLAIMED" and order.claimed_by == admin_id:
        return order

    if order.status == "WAITING_OPERATOR":
        order.status = "CLAIMED"
        order.claimed_by = admin_id
        order.claimed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(order)
        return order

    return "already_claimed"

def approve_order(db: Session, order_id: int, admin_id: int):
    try:
        order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
        if not order:
            return None
        if order.status == "COMPLETED":
            return "already_completed"
        if order.status != "CLAIMED":
            return "invalid_status"
        if order.claimed_by is not None and order.claimed_by != admin_id:
            return "forbidden"
        now = datetime.now(timezone.utc)
        order.status = "COMPLETED"
        order.completed_by = admin_id
        order.completed_at = now
        confirm_locked(db, order.promotion_id)
        award_first_shop_bonus(db, order.telegram_id)
        if order.claimed_at:
            claimed_at = order.claimed_at if order.claimed_at.tzinfo else order.claimed_at.replace(tzinfo=timezone.utc)
            order.processing_seconds = int((now - claimed_at).total_seconds())
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(order)
    return order


def reject_order(
    db: Session,
    order_id: int,
    admin_id: int,
    reason: str,
):
    try:
        order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
        if not order:
            return None
        if order.status != "CLAIMED":
            return "invalid_status"
        if order.claimed_by is not None and order.claimed_by != admin_id:
            return "forbidden"
        if not _refund_locked_order(db, order, "ORDER_REJECT_REFUND"):
            return "wallet_not_found"
        now = datetime.now(timezone.utc)
        order.status = "REJECTED"
        order.rejected_by = admin_id
        order.rejected_at = now
        order.reject_reason = reason
        release_locked(db, order.promotion_id)
        if order.claimed_at:
            claimed_at = order.claimed_at if order.claimed_at.tzinfo else order.claimed_at.replace(tzinfo=timezone.utc)
            order.processing_seconds = int((now - claimed_at).total_seconds())
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(order)
    return order


def _refund_locked_order(db: Session, order: Order, transaction_type: str) -> bool:
    wallet = get_wallet_for_update(db, order.telegram_id)
    if not wallet:
        return False
    before = Decimal(str(wallet.uzs_balance))
    amount = Decimal(str(order.locked_price))
    result = add_uzs(db=db, telegram_id=order.telegram_id, amount=amount)
    if not result:
        return False
    create_transaction(
        db=db, telegram_id=order.telegram_id, currency="UZS", amount=amount,
        balance_before=before, balance_after=Decimal(str(result.uzs_balance)),
        type=transaction_type, description=f"Refund for cancelled Order #{order.id}", commit=False,
    )
    return True


def cancel_order(db: Session, order_id: int, reason: str = "Order cancelled"):
    try:
        order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
        if order is None:
            return None
        if order.status == "CANCELLED":
            return order
        if order.status not in {"WAITING_OPERATOR", "CLAIMED"}:
            return "invalid_status"
        if not _refund_locked_order(db, order, "ORDER_CANCEL_REFUND"):
            return "wallet_not_found"
        release_locked(db, order.promotion_id)
        order.status = "CANCELLED"
        order.cancelled_at = datetime.now(timezone.utc)
        order.cancel_reason = reason
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(order)
    return order
