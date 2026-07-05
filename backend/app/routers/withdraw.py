from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.withdraw import (
    create_withdraw,
    get_withdraws,
    get_pending_withdraws,
    get_completed_withdraws,
    approve_withdraw,
    reject_withdraw,
)
from app.schemas.withdraw import WithdrawCreate

router = APIRouter(
    prefix="/withdraw",
    tags=["Withdraw"],
)


@router.post("/create")
def create_withdraw_request(
    data: WithdrawCreate,
    db: Session = Depends(get_db),
):
    withdraw = create_withdraw(db, data)

    if withdraw == "insufficient":
        return {"message": "Balans yetarli emas"}

    if not withdraw:
        return {"message": "Wallet topilmadi"}

    return {
        "message": "Pul yechish so‘rovi qabul qilindi. To‘lov 24 soat ichida yuboriladi.",
        "withdraw_id": withdraw.id,
        "telegram_id": withdraw.telegram_id,
        "amount": float(withdraw.amount),
        "status": withdraw.status,
    }


@router.get("/all")
def all_withdraws(db: Session = Depends(get_db)):
    return get_withdraws(db)


@router.get("/pending")
def pending_withdraws(db: Session = Depends(get_db)):
    return get_pending_withdraws(db)


@router.get("/completed")
def completed_withdraws(db: Session = Depends(get_db)):
    return get_completed_withdraws(db)


@router.post("/approve/{withdraw_id}")
def approve_withdraw_request(
    withdraw_id: int,
    admin_id: int,
    db: Session = Depends(get_db),
):
    withdraw = approve_withdraw(db, withdraw_id, admin_id)

    if withdraw == "locked":
        return {"message": "Locked balans yetarli emas"}

    if withdraw == "approved":
        return {"message": "Withdraw oldin tasdiqlangan"}

    if withdraw == "rejected":
        return {"message": "Withdraw oldin rad etilgan"}

    if not withdraw:
        return {"message": "Withdraw topilmadi"}

    return {
        "message": "Withdraw tasdiqlandi",
        "withdraw_id": withdraw.id,
        "status": withdraw.status,
        "approved_by": withdraw.approved_by,
    }


@router.post("/reject/{withdraw_id}")
def reject_withdraw_request(
    withdraw_id: int,
    admin_id: int,
    db: Session = Depends(get_db),
):
    withdraw = reject_withdraw(db, withdraw_id, admin_id)

    if withdraw == "locked":
        return {"message": "Locked balans yetarli emas"}

    if withdraw == "approved":
        return {"message": "Withdraw oldin tasdiqlangan"}

    if withdraw == "rejected":
        return {"message": "Withdraw oldin rad etilgan"}

    if not withdraw:
        return {"message": "Withdraw topilmadi"}

    return {
        "message": "Withdraw rad etildi, pul balansga qaytarildi",
        "withdraw_id": withdraw.id,
        "status": withdraw.status,
        "approved_by": withdraw.approved_by,
    }
