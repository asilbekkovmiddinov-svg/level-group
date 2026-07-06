from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.wheel import (
    spin_wheel,
    get_wheel_status,
    fill_coin_order_details,
    get_pending_coin_orders,
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
