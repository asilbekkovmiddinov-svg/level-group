from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import (
    DEPOSIT_BANK_NAME,
    DEPOSIT_CARD_HOLDER,
    DEPOSIT_CARD_NUMBER,
)
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
from app.core.timezone import format_tashkent_datetime
from app.routers.internal_wallet import require_internal_api_key
from app.core.observability import enforce_rate_limit, increment

router = APIRouter(prefix="/deposit", tags=["Deposit"])


def deposit_response(deposit):
    return {
        "deposit_id": deposit.id, "telegram_id": deposit.telegram_id,
        "amount": float(deposit.amount), "status": deposit.status,
        "receipt_uploaded": bool(deposit.receipt_object_key),
        "receipt_content_type": deposit.receipt_content_type,
        "receipt_size": deposit.receipt_size,
        "created_at": format_tashkent_datetime(getattr(deposit, "created_at", None)),
        "receipt_at": format_tashkent_datetime(deposit.receipt_uploaded_at),
        "receipt_uploaded_at": format_tashkent_datetime(deposit.receipt_uploaded_at),
        "approved_at": format_tashkent_datetime(getattr(deposit, "approved_at", None)),
        "rejected_at": format_tashkent_datetime(getattr(deposit, "rejected_at", None)),
        "processing_seconds": getattr(deposit, "processing_seconds", None),
    }


def deposit_payment_details():
    details = {
        "card_number": (DEPOSIT_CARD_NUMBER or "").strip(),
        "card_holder": (DEPOSIT_CARD_HOLDER or "").strip(),
        "bank_name": (DEPOSIT_BANK_NAME or "").strip(),
    }
    if not all(details.values()):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Deposit payment details are not configured",
        )
    return details


def deposit_create_response(deposit):
    payment_details = deposit_payment_details()
    return {
        "message": "Deposit request created",
        **deposit_response(deposit),
        **payment_details,
        "payment_details": payment_details,
    }


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
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
):
    enforce_rate_limit(current_user.telegram_id, "deposit_create", 5)
    deposit = create_deposit(db, data, current_user.telegram_id, idempotency_key)
    increment("deposit_create_total")

    if deposit == "invalid_amount":
        raise HTTPException(status_code=400, detail="Deposit amount must be greater than zero")
    if deposit == "minimum_amount":
        raise HTTPException(status_code=400, detail="Minimal deposit summasi 15 000 UZS")
    if deposit == "idempotency_conflict":
        raise HTTPException(status_code=409, detail="Idempotency key payload mismatch")
    if deposit == "operation_failed":
        raise HTTPException(status_code=500, detail="Deposit request failed")

    return deposit_create_response(deposit)


@router.get("/all")
def all_deposits(
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    return [deposit_response(deposit) for deposit in get_deposits(db)]


@router.get("/pending")
def pending_deposits(
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    return [deposit_response(deposit) for deposit in get_pending_deposits(db)]


@router.get("/claimed")
def claimed_deposits(
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    return [deposit_response(deposit) for deposit in get_claimed_deposits(db)]


@router.post("/{deposit_id}/claim")
def claim_deposit_request(
    deposit_id: int,
    data: DepositAdminAction,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    deposit = claim_deposit(db, deposit_id, data.admin_id, data.receipt_revision)

    if not deposit:
        raise HTTPException(status_code=404, detail="Deposit not found")

    if deposit == "already_claimed":
        raise HTTPException(status_code=409, detail="Deposit is not pending")
    if deposit == "receipt_replaced":
        raise HTTPException(status_code=409, detail="Deposit receipt was replaced")

    if deposit == "operation_failed":
        raise HTTPException(status_code=500, detail="Deposit claim failed")

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
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    deposit = approve_deposit(db, deposit_id, data.admin_id)

    if not deposit:
        raise HTTPException(status_code=404, detail="Deposit not found")

    if deposit == "invalid_status":
        raise HTTPException(status_code=409, detail="Deposit must be claimed")
    if deposit == "not_owner":
        raise HTTPException(status_code=409, detail="Deposit is claimed by another admin")
    if deposit == "receipt_replaced":
        raise HTTPException(status_code=409, detail="Deposit receipt was replaced")

    if deposit == "wallet_not_found":
        raise HTTPException(status_code=404, detail="Wallet not found")

    if deposit == "operation_failed":
        raise HTTPException(status_code=500, detail="Deposit approve failed")

    username = get_user_display(db, deposit.telegram_id)

    return {
        "message": "Deposit approved",
        "deposit_id": deposit.id,
        "telegram_id": deposit.telegram_id,
        "username": username,
        "amount": float(deposit.amount),
        "status": deposit.status,
        "approved_by": getattr(deposit, "approved_by", None),
        "approved_at": format_tashkent_datetime(getattr(deposit, "approved_at", None)),
        "processing_seconds": getattr(deposit, "processing_seconds", 0),
    }


@router.post("/{deposit_id}/reject")
def reject_deposit_request(
    deposit_id: int,
    data: DepositReject,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    deposit = reject_deposit(
        db=db,
        deposit_id=deposit_id,
        admin_id=data.admin_id,
        reason=data.reason,
    )

    if not deposit:
        raise HTTPException(status_code=404, detail="Deposit not found")

    if deposit == "invalid_status":
        raise HTTPException(status_code=409, detail="Deposit must be claimed")
    if deposit == "not_owner":
        raise HTTPException(status_code=409, detail="Deposit is claimed by another admin")
    if deposit == "receipt_replaced":
        raise HTTPException(status_code=409, detail="Deposit receipt was replaced")

    if deposit == "operation_failed":
        raise HTTPException(status_code=500, detail="Deposit reject failed")

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
        "rejected_at": format_tashkent_datetime(getattr(deposit, "rejected_at", None)),
        "processing_seconds": getattr(deposit, "processing_seconds", 0),
    }
