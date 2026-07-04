from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.product import Product
from app.crud.wallet import get_wallet
from app.crud.transaction import create_transaction
from app.schemas.order import OrderCreate
from app.crud.wallet import add_uzs

def create_order(db: Session, data: OrderCreate):
    product = db.query(Product).filter(
        Product.id == data.product_id,
        Product.is_active == True
    ).first()

    if not product:
        return "product_not_found"

    wallet = get_wallet(db, data.telegram_id)

    if not wallet:
        return "wallet_not_found"

    price = Decimal(str(product.price_uzs))

    if wallet.uzs_balance < price:
        return "insufficient_balance"

    before = wallet.uzs_balance

    wallet.uzs_balance = wallet.uzs_balance - price

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
    return db.query(Order).order_by(
        Order.id.desc()
    ).all()


def get_user_orders(db: Session, telegram_id: int):
    return db.query(Order).filter(
        Order.telegram_id == telegram_id
    ).order_by(Order.id.desc()).all()


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

    before, after = add_uzs(
        db=db,
        telegram_id=order.telegram_id,
        amount=float(order.price_uzs)
    )

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
