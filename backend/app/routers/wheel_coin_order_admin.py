from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.services.wheel_coin_order_admin import cancel_wheel_coin_order


router = APIRouter(prefix="/admin/wheel/coin-orders", tags=["Admin Wheel Coin Orders"])


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
        "data": {
            "id": order.id,
            "telegram_id": order.telegram_id,
            "status": order.status,
            "updated_at": order.updated_at,
        },
    }
