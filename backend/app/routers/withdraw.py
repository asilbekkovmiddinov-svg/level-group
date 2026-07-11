from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.withdraw import (
    create_withdraw,
    claim_withdraw,
    get_withdraws,
    get_pending_withdraws,
    get_completed_withdraws,
    approve_withdraw,
    reject_withdraw,
)
from app.schemas.withdraw import WithdrawCreate
from app.core.telegram_auth import TelegramUser, get_current_telegram_user

router = APIRouter(
    prefix="/withdraw",
    tags=["Withdraw"],
)


def withdraw_response(withdraw):
    return {
        "withdraw_id": withdraw.id,
        "telegram_id": withdraw.telegram_id,
        "amount": float(withdraw.amount),
        "card_number": withdraw.card_number,
        "card_holder": withdraw.card_holder,
        "bank_name": withdraw.bank_name,
        "status": withdraw.status,
        "created_at": withdraw.created_at,
        "claimed_by": withdraw.claimed_by,
        "claimed_at": withdraw.claimed_at,
        "approved_by": withdraw.approved_by,
        "approved_at": withdraw.approved_at,
        "rejected_by": withdraw.rejected_by,
        "rejected_at": withdraw.rejected_at,
        "reject_reason": withdraw.reject_reason,
        "processing_seconds": withdraw.processing_seconds,
    }


@router.post("/create", status_code=status.HTTP_201_CREATED)
def create_withdraw_request(
    data: WithdrawCreate,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    withdraw = create_withdraw(db, data, current_user.telegram_id)

    if withdraw == "insufficient":
        raise HTTPException(status_code=400, detail="Balans yetarli emas")
    if withdraw == "minimum_amount":
        raise HTTPException(status_code=400, detail="Minimal withdraw summasi 15 000 UZS")
    if withdraw == "invalid_amount":
        raise HTTPException(status_code=400, detail="Withdraw amount must be greater than zero")
    if withdraw == "operation_failed":
        raise HTTPException(status_code=500, detail="Withdraw request failed")
    if withdraw == "wallet_not_found" or not withdraw:
        raise HTTPException(status_code=404, detail="Wallet topilmadi")

    response = withdraw_response(withdraw)
    response["message"] = "Pul yechish so‘rovi qabul qilindi. To‘lov 24 soat ichida yuboriladi."
    return response


@router.post("/{withdraw_id}/claim")
def claim_withdraw_request(withdraw_id: int, admin_id: int, db: Session = Depends(get_db)):
    withdraw = claim_withdraw(db, withdraw_id, admin_id)

    if withdraw == "already_claimed":
        return {"message": "Withdraw already claimed"}

    if withdraw == "not_pending":
        return {"message": "Withdraw is not pending"}

    if withdraw == "operation_failed":
        return {"message": "Withdraw claim failed"}

    if not withdraw:
        return {"message": "Withdraw topilmadi"}

    response = withdraw_response(withdraw)
    response["message"] = "Withdraw claimed"
    return response


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
def approve_withdraw_request(withdraw_id: int, admin_id: int, db: Session = Depends(get_db)):
    withdraw = approve_withdraw(db, withdraw_id, admin_id)

    if withdraw == "not_owner":
        return {"message": "Withdraw boshqa admin tomonidan qabul qilingan"}

    if withdraw == "locked":
        return {"message": "Locked balans yetarli emas"}

    if withdraw == "approved":
        return {"message": "Withdraw oldin tasdiqlangan"}

    if withdraw == "rejected":
        return {"message": "Withdraw oldin rad etilgan"}

    if withdraw == "not_claimed":
        return {"message": "Withdraw avval claim qilinishi kerak"}

    if withdraw == "invalid_amount":
        return {"message": "Withdraw summasi noto‘g‘ri"}

    if withdraw == "operation_failed":
        return {"message": "Withdraw approve failed"}

    if not withdraw:
        return {"message": "Withdraw topilmadi"}

    response = withdraw_response(withdraw)
    response["message"] = "Withdraw tasdiqlandi"
    return response


@router.post("/reject/{withdraw_id}")
def reject_withdraw_request(withdraw_id: int, admin_id: int, db: Session = Depends(get_db)):
    withdraw = reject_withdraw(db, withdraw_id, admin_id)

    if withdraw == "not_owner":
        return {"message": "Withdraw boshqa admin tomonidan qabul qilingan"}

    if withdraw == "locked":
        return {"message": "Locked balans yetarli emas"}

    if withdraw == "approved":
        return {"message": "Withdraw oldin tasdiqlangan"}

    if withdraw == "rejected":
        return {"message": "Withdraw oldin rad etilgan"}

    if withdraw == "not_claimed":
        return {"message": "Withdraw avval claim qilinishi kerak"}

    if withdraw == "invalid_amount":
        return {"message": "Withdraw summasi noto‘g‘ri"}

    if withdraw == "operation_failed":
        return {"message": "Withdraw reject failed"}

    if not withdraw:
        return {"message": "Withdraw topilmadi"}

    response = withdraw_response(withdraw)
    response["message"] = "Withdraw rad etildi, pul balansga qaytarildi"
    return response
