from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.withdraw import (
    create_withdraw,
    get_withdraws,
    approve_withdraw
)
from app.schemas.withdraw import WithdrawCreate

router = APIRouter(
    prefix="/withdraw",
    tags=["Withdraw"]
)


@router.post("/create")
def create_withdraw_request(
    data: WithdrawCreate,
    db: Session = Depends(get_db)
):
    withdraw = create_withdraw(db, data)

    if withdraw == "insufficient":
        return {
            "message": "Insufficient balance"
        }

    if not withdraw:
        return {
            "message": "Wallet not found"
        }

    return {
        "message": "Withdraw request created",
        "withdraw_id": withdraw.id,
        "telegram_id": withdraw.telegram_id,
        "amount": float(withdraw.amount),
        "status": withdraw.status
    }


@router.get("/all")
def all_withdraws(
    db: Session = Depends(get_db)
):
    return get_withdraws(db)


@router.post("/approve/{withdraw_id}")
def approve_withdraw_request(
    withdraw_id: int,
    admin_id: int,
    db: Session = Depends(get_db)
):
    withdraw = approve_withdraw(
        db,
        withdraw_id,
        admin_id
    )

    if not withdraw:
        return {
            "message": "Withdraw not found"
        }

    if withdraw == "approved":
        return {
            "message": "Withdraw already approved"
        }

    return {
        "message": "Withdraw approved",
        "withdraw_id": withdraw.id,
        "status": withdraw.status,
        "approved_by": withdraw.approved_by
    }
