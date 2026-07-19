from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.services.wheel_coin_order_admin import (
    cancel_wheel_coin_order,
    list_wheel_coin_orders,
)


router = APIRouter(prefix="/admin/wheel/coin-orders", tags=["Admin Wheel Coin Orders"])


def order_response(order):
    return {
        "id": order.id,
        "telegram_id": order.telegram_id,
        "username": order.username,
        "first_name": order.first_name,
        "coin_amount": order.coin_amount,
        "status": order.status,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


@router.get("")
def list_orders(
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return {
        "success": True,
        "data": [order_response(order) for order in list_wheel_coin_orders(db)],
    }


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    order = cancel_wheel_coin_order(db, order_id, admin.telegram_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Wheel Coin order not found")
    if order == "not_cancellable":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Wheel Coin order cannot be cancelled in its current status",
        )
    return {
        "success": True,
        "data": order_response(order),
    }
