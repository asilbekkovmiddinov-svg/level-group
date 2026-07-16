from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
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
    cancel_order,
)
from app.schemas.order import (
    OrderCreate,
    OrderAdminAction,
    OrderReject,
)
from app.core.telegram_auth import TelegramUser, get_current_telegram_user

router = APIRouter(
    prefix="/orders",
    tags=["Orders"],
)


def order_response(order):
    return {
        "id": order.id,
        "telegram_id": order.telegram_id,
        "product_id": order.product_id,
        "product_title": order.product_title,
        "coins_amount": order.coins_amount,
        "price_uzs": float(order.price_uzs),
        "status": order.status,
        "region": getattr(order, "region", None),
        "claimed_by": getattr(order, "claimed_by", None),
        "claimed_at": (
            str(order.claimed_at)
            if getattr(order, "claimed_at", None)
            else None
        ),
        "completed_by": getattr(order, "completed_by", None),
        "completed_at": (
            str(order.completed_at)
            if getattr(order, "completed_at", None)
            else None
        ),
        "rejected_by": getattr(order, "rejected_by", None),
        "rejected_at": (
            str(order.rejected_at)
            if getattr(order, "rejected_at", None)
            else None
        ),
        "reject_reason": getattr(order, "reject_reason", None),
        "processing_seconds": getattr(order, "processing_seconds", None),
        "created_at": (
            str(order.created_at)
            if getattr(order, "created_at", None)
            else None
        ),
    }


@router.post("/create")
def create_new_order(
    data: OrderCreate,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
):
    if idempotency_key:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key or len(idempotency_key) > 128:
            raise HTTPException(status_code=400, detail="Invalid Idempotency-Key")
    order = create_order(db, data, current_user.telegram_id, idempotency_key)

    if order == "product_not_found":
        return {
            "success": False,
            "message": "Product not found",
        }

    if order == "wallet_not_found":
        return {
            "success": False,
            "message": "Wallet not found",
        }

    if order == "insufficient_balance":
        return {
            "success": False,
            "message": "Balans yetarli emas",
        }

    if order == "idempotency_conflict":
        raise HTTPException(status_code=409, detail="Idempotency key payload mismatch")

    if order == "operation_failed":
        raise HTTPException(status_code=500, detail="Order yaratilmadi")

    if not order:
        return {
            "success": False,
            "message": "Order yaratilmadi",
        }

    return {
        "success": True,
        "message": "Order created",
        "data": order_response(order),
    }


@router.get("/all")
def all_orders(db: Session = Depends(get_db)):
    orders = get_orders(db)

    return {
        "success": True,
        "data": [order_response(order) for order in orders],
    }


@router.get("/pending")
def pending_orders(db: Session = Depends(get_db)):
    orders = get_pending_orders(db)

    return {
        "success": True,
        "data": [order_response(order) for order in orders],
    }


@router.get("/claimed")
def claimed_orders(db: Session = Depends(get_db)):
    orders = get_claimed_orders(db)

    return {
        "success": True,
        "data": [order_response(order) for order in orders],
    }


@router.get("/user")
def user_orders(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    orders = get_user_orders(db, current_user.telegram_id)

    return {
        "success": True,
        "data": [order_response(order) for order in orders],
    }


@router.post("/{order_id}/claim")
def claim_existing_order(
    order_id: int,
    data: OrderAdminAction,
    db: Session = Depends(get_db),
):
    order = claim_order(db, order_id, data.admin_id)

    if not order:
        return {
            "success": False,
            "message": "Order not found",
        }

    if order == "already_claimed":
        return {
            "success": False,
            "message": "Order already claimed",
        }

    return {
        "success": True,
        "message": "Order claimed",
        "data": order_response(order),
    }


@router.post("/{order_id}/approve")
def approve_existing_order(
    order_id: int,
    data: OrderAdminAction,
    db: Session = Depends(get_db),
):
    order = approve_order(db, order_id, data.admin_id)

    if not order:
        return {
            "success": False,
            "message": "Order not found",
        }

    if order == "already_completed":
        return {
            "success": False,
            "message": "Order already completed",
        }

    if order == "invalid_status":
        return {
            "success": False,
            "message": "Invalid order status",
        }

    return {
        "success": True,
        "message": "Order approved",
        "data": order_response(order),
    }


@router.post("/{order_id}/reject")
def reject_existing_order(
    order_id: int,
    data: OrderReject,
    db: Session = Depends(get_db),
):
    order = reject_order(
        db,
        order_id,
        data.admin_id,
        data.reason,
    )

    if not order:
        return {
            "success": False,
            "message": "Order not found",
        }

    if order == "invalid_status":
        return {
            "success": False,
            "message": "Invalid order status",
        }

    if order == "wallet_not_found":
        return {
            "success": False,
            "message": "Wallet not found",
        }

    return {
        "success": True,
        "message": "Order rejected",
        "data": order_response(order),
    }


@router.post("/cancel/{order_id}")
def cancel_existing_order(
    order_id: int,
    db: Session = Depends(get_db),
):
    order = cancel_order(db, order_id)

    if not order:
        return {
            "success": False,
            "message": "Order not found",
        }

    if order == "already_cancelled":
        return {
            "success": False,
            "message": "Order already cancelled",
        }

    if order == "already_completed":
        return {
            "success": False,
            "message": "Completed order cannot be cancelled",
        }

    if order == "wallet_not_found":
        return {
            "success": False,
            "message": "Wallet not found",
        }

    return {
        "success": True,
        "message": "Order cancelled",
        "data": order_response(order),
}
