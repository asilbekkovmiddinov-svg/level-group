from decimal import Decimal
from datetime import datetime, timezone
from hashlib import sha256
import logging
import secrets

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.product import Product
from app.schemas.order import OrderCreate
from app.crud.wallet import get_wallet_for_update, add_uzs
from app.crud.transaction import create_transaction
from app.services.referrals import award_first_shop_bonus


logger = logging.getLogger(__name__)


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

            price = Decimal(str(product.price_uzs))
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
                price_uzs=product.price_uzs,
                region=region,
                platform=platform,
                status="WAITING_OPERATOR",
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
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
    order = db.query(Order).filter(
        Order.id == order_id
    ).first()

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
    award_first_shop_bonus(db, order.telegram_id)

    if order.claimed_at:
        claimed_at = order.claimed_at if order.claimed_at.tzinfo else order.claimed_at.replace(tzinfo=timezone.utc)
        order.processing_seconds = int(
            (now - claimed_at).total_seconds()
        )

    db.commit()
    db.refresh(order)

    return order


def reject_order(
    db: Session,
    order_id: int,
    admin_id: int,
    reason: str,
):
    order = db.query(Order).filter(
        Order.id == order_id
    ).first()

    if not order:
        return None

    if order.status != "CLAIMED":
        return "invalid_status"
    if order.claimed_by is not None and order.claimed_by != admin_id:
        return "forbidden"

    wallet = get_wallet_for_update(db, order.telegram_id)
    if not wallet:
        return "wallet_not_found"
    before = Decimal(str(wallet.uzs_balance))

    result = add_uzs(
        db=db,
        telegram_id=order.telegram_id,
        amount=order.price_uzs,
    )

    if not result:
        return "wallet_not_found"

    after = Decimal(str(result.uzs_balance))

    create_transaction(
        db=db,
        telegram_id=order.telegram_id,
        currency="UZS",
        amount=order.price_uzs,
        balance_before=before,
        balance_after=after,
        type="ORDER_REJECT_REFUND",
        description=f"Refund for rejected Order #{order.id}",
        commit=False,
    )

    now = datetime.now(timezone.utc)

    order.status = "REJECTED"
    order.rejected_by = admin_id
    order.rejected_at = now
    order.reject_reason = reason

    if order.claimed_at:
        claimed_at = order.claimed_at if order.claimed_at.tzinfo else order.claimed_at.replace(tzinfo=timezone.utc)
        order.processing_seconds = int(
            (now - claimed_at).total_seconds()
        )

    db.commit()
    db.refresh(order)

    return order
