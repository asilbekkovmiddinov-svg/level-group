import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import INTERNAL_API_KEY
from app.core.database import get_db
from app.crud.user import get_user
from app.crud.wallet import get_wallet
from app.crud.withdraw import create_withdraw
from app.crud.deposit import create_deposit
from app.schemas.withdraw import InternalWithdrawCreate
from app.schemas.deposit import InternalDepositCreate
from app.schemas.user import InternalUserRegister
from app.models.deposit import Deposit
from app.services.internal_users import (
    InternalUserServiceError,
    mark_internal_user_seen,
    register_internal_user,
)
from app.services.object_storage import StorageOperationError, generate_presigned_get_url
from app.services.deposit_notifications import (
    DepositNotificationAlreadySentError,
    DepositNotificationAttemptsExceededError,
    DepositNotificationInProgressError,
    DepositNotificationNotFoundError,
    DepositNotificationStateError,
    DepositReceiptMissingError,
    send_deposit_receipt_notification,
)
from app.services.withdraw_notifications import (
    WithdrawNotificationAlreadySentError,
    WithdrawNotificationAttemptsExceededError,
    WithdrawNotificationInProgressError,
    WithdrawNotificationNotFoundError,
    WithdrawNotificationStateError,
    send_withdraw_notification,
)


router = APIRouter(prefix="/internal", tags=["Internal"])


def require_internal_api_key(
    x_internal_api_key: Annotated[str | None, Header()] = None,
):
    if (
        not INTERNAL_API_KEY
        or not x_internal_api_key
        or not hmac.compare_digest(x_internal_api_key, INTERNAL_API_KEY)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal service access is forbidden",
        )


@router.post("/users/register", status_code=status.HTTP_201_CREATED)
def internal_register_user(
    data: InternalUserRegister,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    try:
        result = register_internal_user(db, data)
    except InternalUserServiceError:
        raise HTTPException(500, "Internal user registration failed")
    return {
        "success": True,
        "data": {
            "telegram_id": result.telegram_id,
            "created": result.created,
            "wallet_created": result.wallet_created,
        },
        "message": None,
    }


@router.post("/users/{telegram_id}/seen")
def internal_user_seen(
    telegram_id: int,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    if telegram_id <= 0:
        raise HTTPException(400, "Invalid Telegram ID")
    try:
        updated = mark_internal_user_seen(db, telegram_id)
    except InternalUserServiceError:
        raise HTTPException(500, "Internal user activity update failed")
    if not updated:
        raise HTTPException(404, "User not found")
    return {"success": True, "data": {"telegram_id": telegram_id}, "message": None}


@router.get("/wallet/{telegram_id}")
def internal_wallet_info(
    telegram_id: int,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    user = get_user(db, telegram_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    wallet = get_wallet(db, telegram_id)
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found",
        )

    return {
        "telegram_id": wallet.telegram_id,
        "efc_balance": float(wallet.efc_balance),
        "uzs_balance": float(wallet.uzs_balance),
        "locked_efc": float(wallet.locked_efc),
        "locked_uzs": float(wallet.locked_uzs),
    }


@router.post("/withdraw/create", status_code=status.HTTP_201_CREATED)
def internal_create_withdraw(
    data: InternalWithdrawCreate,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    withdraw = create_withdraw(db, data, data.telegram_id)
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

    return {
        "withdraw_id": withdraw.id,
        "telegram_id": withdraw.telegram_id,
        "amount": float(withdraw.amount),
        "card_number": withdraw.card_number,
        "card_holder": withdraw.card_holder,
        "bank_name": withdraw.bank_name,
        "status": withdraw.status,
        "created_at": withdraw.created_at,
        "message": "Pul yechish so‘rovi qabul qilindi. To‘lov 24 soat ichida yuboriladi.",
    }


@router.post("/deposit/create", status_code=status.HTTP_201_CREATED)
def internal_create_deposit(
    data: InternalDepositCreate,
    _: None = Depends(require_internal_api_key),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
):
    deposit = create_deposit(db, data, data.telegram_id, idempotency_key)
    if deposit == "invalid_amount":
        raise HTTPException(status_code=400, detail="Deposit amount must be greater than zero")
    if deposit == "minimum_amount":
        raise HTTPException(status_code=400, detail="Minimal deposit summasi 15 000 UZS")
    if deposit == "idempotency_conflict":
        raise HTTPException(status_code=409, detail="Idempotency key payload mismatch")
    if deposit == "operation_failed":
        raise HTTPException(status_code=500, detail="Deposit request failed")
    return {"message": "Deposit request created", "deposit_id": deposit.id, "telegram_id": deposit.telegram_id, "amount": float(deposit.amount), "status": deposit.status}

@router.get("/deposits/{deposit_id}/receipt-url")
def internal_deposit_receipt_url(deposit_id: int, _: None = Depends(require_internal_api_key), db: Session = Depends(get_db)):
    deposit = db.query(Deposit).filter(Deposit.id == deposit_id).first()
    if not deposit or not deposit.receipt_object_key:
        raise HTTPException(404, "Receipt not found")
    try:
        return {"url": generate_presigned_get_url(deposit.receipt_object_key)}
    except StorageOperationError:
        raise HTTPException(500, "Receipt access is unavailable")


@router.post("/deposits/{deposit_id}/send-receipt-notification")
def send_deposit_receipt_notification_request(
    deposit_id: int,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    try:
        result = send_deposit_receipt_notification(db, deposit_id)
    except (DepositNotificationNotFoundError, DepositReceiptMissingError):
        raise HTTPException(404, "Deposit receipt not found")
    except (
        DepositNotificationAlreadySentError,
        DepositNotificationInProgressError,
        DepositNotificationAttemptsExceededError,
        DepositNotificationStateError,
    ):
        raise HTTPException(409, "Receipt notification cannot be started")

    if result.status == "FAILED":
        raise HTTPException(
            503 if result.retryable else 500,
            "Receipt notification delivery failed",
        )

    return {
        "status": result.status,
        "message_id": result.message_id,
        "attempts": result.attempts,
        "sent_at": result.sent_at,
    }


@router.post("/withdraws/{withdraw_id}/send-notification")
def send_withdraw_notification_request(
    withdraw_id: int,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    try:
        result = send_withdraw_notification(db, withdraw_id)
    except WithdrawNotificationNotFoundError:
        raise HTTPException(404, "Withdraw not found")
    except (
        WithdrawNotificationAlreadySentError,
        WithdrawNotificationInProgressError,
        WithdrawNotificationAttemptsExceededError,
        WithdrawNotificationStateError,
    ):
        raise HTTPException(409, "Withdraw notification cannot be started")

    if result.status == "FAILED":
        raise HTTPException(
            503 if result.retryable else 500,
            "Withdraw notification delivery failed",
        )

    return {
        "status": result.status,
        "message_id": result.message_id,
        "attempts": result.attempts,
        "sent_at": result.sent_at,
    }
