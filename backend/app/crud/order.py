from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.product import Product
from app.schemas.order import OrderCreate
from app.crud.wallet import get_wallet, add_uzs
from app.crud.transaction import create_transaction


def create_order(db: Session, data: OrderCreate):
    product = (
        db.query(Product)
        .filter(
            Product.id == data.product_id,
            Product.is_active == True
        )
        .first()
    )

    if not product:
        return "product_not_found"

    wallet = get_wallet(db, data.telegram_id)

    if not wallet:
        return "wallet_not_found"

    price = Decimal(str(product.price_uzs))

    if wallet.uzs_balance < price:
        return "insufficient_balance"

    before = wallet.uzs_balance
    wallet.uzs_balance -= price

    order = Order(
        telegram_id=data.telegram_id,
        product_id=product.id,
        product_title=product.title,
        coins_amount=product.coins_amount,
        price_uzs=product.price_uzs,
        status="PENDING"
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    create_transaction(
        db=db,
        telegram_id=data.telegram_id,
        currency="UZS",
        amount=float(product.price_uzs),
        balance_before=before,
        balance_after=wallet.uzs_balance,
        type="ORDER_PAYMENT",
        description=f"Order payment for {product.title}"
    )

    return order


def get_orders(db: Session):
    return (
        db.query(Order)
        .order_by(Order.id.desc())
        .all()
    )


def get_user_orders(db: Session, telegram_id: int):
    return (
        db.query(Order)
        .filter(Order.telegram_id == telegram_id)
        .order_by(Order.id.desc())
        .all()
    )


def get_pending_orders(db: Session):
    return (
        db.query(Order)
        .filter(Order.status == "PENDING")
        .order_by(Order.id.asc())
        .all()
    )


def get_claimed_orders(db: Session):
    return (
        db.query(Order)
        .filter(Order.status == "CLAIMED")
        .order_by(Order.claimed_at.asc())
        .all()
    )
def update_order_status(db: Session, order_id: int, status: str):
    order = db.query(Order).filter(
        Order.id == order_id
    ).first()

    if not order:
        return None

    order.status = status

    db.commit()
    db.refresh(order)

    return order


def claim_order(db: Session, order_id: int, admin_id: int):
    order = db.query(Order).filter(
        Order.id == order_id
    ).first()

    if not order:
        return None

    if order.status != "PENDING":
        return "already_claimed"

    order.status = "CLAIMED"
    order.claimed_by = admin_id
    order.claimed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(order)

    return order


def approve_order(db: Session, order_id: int, admin_id: int):
    order = db.query(Order).filter(
        Order.id == order_id
    ).first()

    if not order:
        return None

    if order.status == "COMPLETED":
        return "already_completed"

    if order.status not in ["CLAIMED", "PENDING"]:
        return "invalid_status"

    now = datetime.now(timezone.utc)

    order.status = "COMPLETED"
    order.completed_by = admin_id
    order.completed_at = now

    if order.claimed_at:
        order.processing_seconds = int(
            (now - order.claimed_at).total_seconds()
        )

    db.commit()
    db.refresh(order)

    return order


def reject_order(
    db: Session,
    order_id: int,
    admin_id: int,
    reason: str
):
    order = db.query(Order).filter(
        Order.id == order_id
    ).first()

    if not order:
        return None

    if order.status in ["COMPLETED", "REJECTED", "CANCELLED"]:
        return "invalid_status"

    result = add_uzs(
        db=db,
        telegram_id=order.telegram_id,
        amount=float(order.price_uzs)
    )

    if not result:
        return "wallet_not_found"

    before, after = result

    create_transaction(
        db=db,
        telegram_id=order.telegram_id,
        currency="UZS",
        amount=float(order.price_uzs),
        balance_before=before,
        balance_after=after,
        type="ORDER_REJECT_REFUND",
        description=f"Refund for rejected Order #{order.id}"
    )

    now = datetime.now(timezone.utc)

    order.status = "REJECTED"
    order.rejected_by = admin_id
    order.rejected_at = now
    order.reject_reason = reason

    if order.claimed_at:
        order.processing_seconds = int(
            (now - order.claimed_at).total_seconds()
        )

    db.commit()
    db.refresh(order)

    return order


def cancel_order(db: Session, order_id: int):
    order = db.query(Order).filter(
        Order.id == order_id
    ).first()

    if not order:
        return None

    if order.status == "CANCELLED":
        return "already_cancelled"

    if order.status == "COMPLETED":
        return "already_completed"

    result = add_uzs(
        db=db,
        telegram_id=order.telegram_id,
        amount=float(order.price_uzs)
    )

    if not result:
        return "wallet_not_found"

    before, after = result

    create_transaction(
        db=db,
        telegram_id=order.telegram_id,
        currency="UZS",
        amount=float(order.price_uzs),
        balance_before=before,
        balance_after=after,
        type="ORDER_REFUND",
        description=f"Refund for Order #{order.id}"
    )

    order.status = "CANCELLED"

    db.commit()
    db.refresh(order)

    return order
