from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.wheel import (
    spin_wheel,
    get_wheel_status,
    fill_coin_order_details,
    get_pending_coin_orders,
    approve_coin_order,
    reject_coin_order,
)
from app.schemas.wheel import (
    WheelSpinRequest,
    WheelCoinOrderCreate,
)

router = APIRouter(
    prefix="/wheel",
    tags=["Wheel"],
)


def coin_order_response(order):
    return {
        "id": order.id,
        "spin_id": order.spin_id,
        "telegram_id": order.telegram_id,
        "username": order.username,
        "first_name": order.first_name,
        "coin_amount": order.coin_amount,
        "konami_login": order.konami_login,
        "region": order.region,
        "device": order.device,
        "status": order.status,
    }


@router.get("/status/{telegram_id}")
def wheel_status(
    telegram_id: int,
    db: Session = Depends(get_db),
):
    return get_wheel_status(
        db=db,
        telegram_id=telegram_id,
    )


@router.post("/spin")
def wheel_spin(
    data: WheelSpinRequest,
    db: Session = Depends(get_db),
):
    return spin_wheel(
        db=db,
        telegram_id=data.telegram_id,
        spin_type=data.spin_type,
    )


@router.post("/coin-order/details")
def coin_order_details(
    data: WheelCoinOrderCreate,
    db: Session = Depends(get_db),
):
    order = fill_coin_order_details(
        db=db,
        telegram_id=data.telegram_id,
        konami_login=data.konami_login,
        konami_password=data.konami_password,
        region=data.region,
        device=data.device,
    )

    if not order:
        return {
            "success": False,
            "message": "Kutilayotgan coin buyurtma topilmadi",
        }

    return {
        "success": True,
        "message": "Coin buyurtma adminga yuborildi",
        "data": coin_order_response(order),
    }


@router.get("/coin-orders/pending")
def pending_coin_orders(
    db: Session = Depends(get_db),
):
    orders = get_pending_coin_orders(db)

    return {
        "success": True,
        "data": [coin_order_response(order) for order in orders],
    }
@router.post("/coin-orders/{order_id}/approve")
def approve_wheel_coin_order(
    order_id: int,
    admin_id: int,
    db: Session = Depends(get_db),
):
    order = approve_coin_order(
        db=db,
        order_id=order_id,
        admin_id=admin_id,
    )

    if order == "not_pending":
        return {"success": False, "message": "Buyurtma kutilayotgan holatda emas"}

    if not order:
        return {"success": False, "message": "Buyurtma topilmadi"}

    return {
        "success": True,
        "message": "Coin buyurtma bajarildi",
        "data": coin_order_response(order),
    }


@router.post("/coin-orders/{order_id}/reject")
def reject_wheel_coin_order(
    order_id: int,
    admin_id: int,
    reason: str = "Admin rad etdi",
    db: Session = Depends(get_db),
):
    order = reject_coin_order(
        db=db,
        order_id=order_id,
        admin_id=admin_id,
        reason=reason,
    )

    if order == "not_pending":
        return {"success": False, "message": "Buyurtma kutilayotgan holatda emas"}

    if not order:
        return {"success": False, "message": "Buyurtma topilmadi"}

    return {
        "success": True,
        "message": "Coin buyurtma rad etildi",
        "data": coin_order_response(order),
    }
