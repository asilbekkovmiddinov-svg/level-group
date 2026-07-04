from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.order import (
    create_order,
    get_orders,
    get_user_orders,
    update_order_status,
    cancel_order
)
from app.schemas.order import OrderCreate, OrderStatusUpdate

router = APIRouter(
    prefix="/orders",
    tags=["Orders"]
)
@router.post("/create")
def create_new_order(
    data: OrderCreate,
    db: Session = Depends(get_db)
):
    order = create_order(db, data)

    if order == "product_not_found":
        return {"message": "Product not found"}

    if order == "wallet_not_found":
        return {"message": "Wallet not found"}

    if order == "insufficient_balance":
        return {"message": "Insufficient balance"}

    return {
        "message": "Order created",
        "order_id": order.id,
        "telegram_id": order.telegram_id,
        "product_title": order.product_title,
        "coins_amount": order.coins_amount,
        "price_uzs": float(order.price_uzs),
        "status": order.status
    }


@router.get("/all")
def all_orders(db: Session = Depends(get_db)):
    return get_orders(db)


@router.get("/user/{telegram_id}")
def user_orders(
    telegram_id: int,
    db: Session = Depends(get_db)
):
    return get_user_orders(db, telegram_id)


@router.put("/status/{order_id}")
def change_order_status(
    
    order_id: int,
    data: OrderStatusUpdate,
    db: Session = Depends(get_db)
):
    order = update_order_status(db, order_id, data.status)

    if not order:
        return {"message": "Order not found"}

    return {
        "message": "Order status updated",
        "order_id": order.id,
        "status": order.status
    }


@router.post("/cancel/{order_id}")
def cancel_existing_order(
    order_id: int,
    db: Session = Depends(get_db)
):
    order = cancel_order(db, order_id)

    if order is None:
        return {
            "message": "Order not found"
        }

    if order == "already_cancelled":
        return {
            "message": "Order already cancelled"
        }

    if order == "already_completed":
        return {
            "message": "Completed order cannot be cancelled"
        }

    return {
        "message": "Order cancelled",
        "order_id": order.id,
        "status": order.status
    }
