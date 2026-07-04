from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.order import (
    create_order,
    get_orders,
    get_user_orders,
    get_pending_orders,
    get_claimed_orders,
    claim_order,
    approve_order,
    reject_order,
    cancel_order
)
from app.schemas.order import (
    OrderCreate,
    OrderAdminAction,
    OrderReject
)

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


@router.get("/pending")
def pending_orders(db: Session = Depends(get_db)):
    return get_pending_orders(db)


@router.get("/claimed")
def claimed_orders(db: Session = Depends(get_db)):
    return get_claimed_orders(db)


@router.get("/user/{telegram_id}")
def user_orders(
    telegram_id: int,
    db: Session = Depends(get_db)
):
    return get_user_orders(db, telegram_id)


@router.post("/{order_id}/claim")
def claim_existing_order(
    order_id: int,
    data: OrderAdminAction,
    db: Session = Depends(get_db)
):
    order = claim_order(db, order_id, data.admin_id)

    if not order:
        return {"message": "Order not found"}

    if order == "already_claimed":
        return {"message": "Order already claimed"}

    return {
        "message": "Order claimed",
        "order_id": order.id,
        "status": order.status,
        "claimed_by": order.claimed_by
    }


@router.post("/{order_id}/approve")
def approve_existing_order(
    order_id: int,
    data: OrderAdminAction,
    db: Session = Depends(get_db)
):
    order = approve_order(db, order_id, data.admin_id)

    if not order:
        return {"message": "Order not found"}

    if order == "already_completed":
        return {"message": "Order already completed"}

    if order == "invalid_status":
        return {"message": "Invalid order status"}

    return {
        "message": "Order approved",
        "order_id": order.id,
        "status": order.status,
        "completed_by": order.completed_by,
        "processing_seconds": order.processing_seconds
    }


@router.post("/{order_id}/reject")
def reject_existing_order(
    order_id: int,
    data: OrderReject,
    db: Session = Depends(get_db)
):
    order = reject_order(
        db,
        order_id,
        data.admin_id,
        data.reason
    )

    if not order:
        return {"message": "Order not found"}

    if order == "invalid_status":
        return {"message": "Invalid order status"}

    if order == "wallet_not_found":
        return {"message": "Wallet not found"}

    return {
        "message": "Order rejected",
        "order_id": order.id,
        "status": order.status,
        "rejected_by": order.rejected_by,
        "reason": order.reject_reason,
        "processing_seconds": order.processing_seconds
    }


@router.post("/cancel/{order_id}")
def cancel_existing_order(
    order_id: int,
    db: Session = Depends(get_db)
):
    order = cancel_order(db, order_id)

    if not order:
        return {"message": "Order not found"}

    if order == "already_cancelled":
        return {"message": "Order already cancelled"}

    if order == "already_completed":
        return {"message": "Completed order cannot be cancelled"}

    if order == "wallet_not_found":
        return {"message": "Wallet not found"}

    return {
        "message": "Order cancelled",
        "order_id": order.id,
        "status": order.status
    }
