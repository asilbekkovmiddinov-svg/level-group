from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.crud.deposit import (
    create_deposit,
    get_deposits,
    get_pending_deposits,
    get_claimed_deposits,
    claim_deposit,
    approve_deposit,
    reject_deposit,
)
from app.schemas.deposit import (
    DepositCreate,
    DepositAdminAction,
    DepositReject,
)
from app.core.telegram_auth import TelegramUser, get_current_telegram_user

router = APIRouter(prefix="/deposit", tags=["Deposit"])


def get_user_display(db: Session, telegram_id: int):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()

    if not user:
        return "Nomaʼlum"

    if user.username:
        return f"@{user.username}"

    if user.first_name:
        return user.first_name

    return "Nomaʼlum"


@router.post("/create", status_code=status.HTTP_201_CREATED)
def create_deposit_request(
    data: DepositCreate,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    deposit = create_deposit(db, data, current_user.telegram_id)

    if deposit == "invalid_amount":
        raise HTTPException(status_code=400, detail="Deposit amount must be greater than zero")
    if deposit == "minimum_amount":
        raise HTTPException(status_code=400, detail="Minimal deposit summasi 15 000 UZS")

    return {
        "message": "Deposit request created",
        "deposit_id": deposit.id,
        "telegram_id": deposit.telegram_id,
        "amount": float(deposit.amount),
        "status": deposit.status,
    }


@router.get("/all")
def all_deposits(db: Session = Depends(get_db)):
    return get_deposits(db)


@router.get("/pending")
def pending_deposits(db: Session = Depends(get_db)):
    return get_pending_deposits(db)


@router.get("/claimed")
def claimed_deposits(db: Session = Depends(get_db)):
    return get_claimed_deposits(db)


@router.post("/{deposit_id}/claim")
def claim_deposit_request(
    deposit_id: int,
    data: DepositAdminAction,
    db: Session = Depends(get_db),
):
    deposit = claim_deposit(db, deposit_id, data.admin_id)

    if not deposit:
        return {"message": "Deposit not found"}

    if deposit == "already_claimed":
        return {"message": "Deposit already claimed"}

    if deposit == "operation_failed":
        return {"message": "Deposit claim failed"}

    return {
        "message": "Deposit claimed",
        "deposit_id": deposit.id,
        "status": deposit.status,
        "claimed_by": getattr(deposit, "claimed_by", None),
    }


@router.post("/{deposit_id}/approve")
def approve_deposit_request(
    deposit_id: int,
    data: DepositAdminAction,
    db: Session = Depends(get_db),
):
    deposit = approve_deposit(db, deposit_id, data.admin_id)

    if not deposit:
        return {"message": "Deposit not found"}

    if deposit == "invalid_status":
        return {"message": "Invalid deposit status"}

    if deposit == "wallet_not_found":
        return {"message": "Wallet not found"}

    if deposit == "operation_failed":
        return {"message": "Deposit approve failed"}

    username = get_user_display(db, deposit.telegram_id)

    return {
        "message": "Deposit approved",
        "deposit_id": deposit.id,
        "telegram_id": deposit.telegram_id,
        "username": username,
        "amount": float(deposit.amount),
        "status": deposit.status,
        "approved_by": getattr(deposit, "approved_by", None),
        "approved_at": getattr(deposit, "approved_at", None),
        "processing_seconds": getattr(deposit, "processing_seconds", 0),
    }


@router.post("/{deposit_id}/reject")
def reject_deposit_request(
    deposit_id: int,
    data: DepositReject,
    db: Session = Depends(get_db),
):
    deposit = reject_deposit(
        db=db,
        deposit_id=deposit_id,
        admin_id=data.admin_id,
        reason=data.reason,
    )

    if not deposit:
        return {"message": "Deposit not found"}

    if deposit == "invalid_status":
        return {"message": "Invalid deposit status"}

    if deposit == "operation_failed":
        return {"message": "Deposit reject failed"}

    username = get_user_display(db, deposit.telegram_id)

    return {
        "message": "Deposit rejected",
        "deposit_id": deposit.id,
        "telegram_id": deposit.telegram_id,
        "username": username,
        "amount": float(deposit.amount),
        "status": deposit.status,
        "rejected_by": getattr(deposit, "rejected_by", data.admin_id),
        "reason": getattr(deposit, "reject_reason", data.reason),
        "processing_seconds": getattr(deposit, "processing_seconds", 0),
    }
