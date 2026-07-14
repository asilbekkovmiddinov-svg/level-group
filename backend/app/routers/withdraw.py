import logging

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
from app.core.timezone import format_tashkent_datetime
from app.routers.internal_wallet import require_internal_api_key
from app.services.withdraw_notifications import send_withdraw_notification

router = APIRouter(
    prefix="/withdraw",
    tags=["Withdraw"],
)
logger = logging.getLogger(__name__)


def withdraw_response(withdraw):
    return {
        "withdraw_id": withdraw.id,
        "telegram_id": withdraw.telegram_id,
        "amount": float(withdraw.amount),
        "card_number": withdraw.card_number,
        "card_holder": withdraw.card_holder,
        "bank_name": withdraw.bank_name,
        "status": withdraw.status,
        "created_at": format_tashkent_datetime(withdraw.created_at),
        "claimed_by": withdraw.claimed_by,
        "claimed_at": format_tashkent_datetime(withdraw.claimed_at),
        "approved_by": withdraw.approved_by,
        "approved_at": format_tashkent_datetime(withdraw.approved_at),
        "rejected_by": withdraw.rejected_by,
        "rejected_at": format_tashkent_datetime(withdraw.rejected_at),
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
    try:
        notification = send_withdraw_notification(db, withdraw.id)
        response["notification_status"] = notification.status
    except Exception:
        db.rollback()
        logger.exception("Withdraw %s admin notification failed unexpectedly", withdraw.id)
        response["notification_status"] = "FAILED"
    response["message"] = "Pul yechish so‘rovi qabul qilindi. To‘lov 24 soat ichida yuboriladi."
    return response


@router.post("/{withdraw_id}/claim")
def claim_withdraw_request(
    withdraw_id: int,
    admin_id: int,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    withdraw = claim_withdraw(db, withdraw_id, admin_id)

    if withdraw == "already_claimed":
        raise HTTPException(status_code=409, detail="Withdraw is already claimed")

    if withdraw == "not_pending":
        raise HTTPException(status_code=409, detail="Withdraw is not pending")

    if withdraw == "operation_failed":
        raise HTTPException(status_code=500, detail="Withdraw claim failed")

    if not withdraw:
        raise HTTPException(status_code=404, detail="Withdraw not found")

    response = withdraw_response(withdraw)
    response["message"] = "Withdraw claimed"
    return response


@router.get("/all")
def all_withdraws(
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    return get_withdraws(db)


@router.get("/pending")
def pending_withdraws(
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    return get_pending_withdraws(db)


@router.get("/completed")
def completed_withdraws(
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    return get_completed_withdraws(db)


@router.post("/approve/{withdraw_id}")
def approve_withdraw_request(
    withdraw_id: int,
    admin_id: int,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    withdraw = approve_withdraw(db, withdraw_id, admin_id)

    if withdraw == "not_owner":
        raise HTTPException(status_code=409, detail="Withdraw is claimed by another admin")

    if withdraw == "locked":
        raise HTTPException(status_code=409, detail="Locked balance is insufficient")

    if withdraw == "approved":
        raise HTTPException(status_code=409, detail="Withdraw is already approved")

    if withdraw == "rejected":
        raise HTTPException(status_code=409, detail="Withdraw is already rejected")

    if withdraw == "not_claimed":
        raise HTTPException(status_code=409, detail="Withdraw must be claimed first")

    if withdraw == "invalid_amount":
        raise HTTPException(status_code=409, detail="Withdraw amount is invalid")

    if withdraw == "operation_failed":
        raise HTTPException(status_code=500, detail="Withdraw approve failed")

    if not withdraw:
        raise HTTPException(status_code=404, detail="Withdraw not found")

    response = withdraw_response(withdraw)
    response["message"] = "Withdraw tasdiqlandi"
    return response


@router.post("/reject/{withdraw_id}")
def reject_withdraw_request(
    withdraw_id: int,
    admin_id: int,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    withdraw = reject_withdraw(db, withdraw_id, admin_id)

    if withdraw == "not_owner":
        raise HTTPException(status_code=409, detail="Withdraw is claimed by another admin")

    if withdraw == "locked":
        raise HTTPException(status_code=409, detail="Locked balance is insufficient")

    if withdraw == "approved":
        raise HTTPException(status_code=409, detail="Withdraw is already approved")

    if withdraw == "rejected":
        raise HTTPException(status_code=409, detail="Withdraw is already rejected")

    if withdraw == "not_claimed":
        raise HTTPException(status_code=409, detail="Withdraw must be claimed first")

    if withdraw == "invalid_amount":
        raise HTTPException(status_code=409, detail="Withdraw amount is invalid")

    if withdraw == "operation_failed":
        raise HTTPException(status_code=500, detail="Withdraw reject failed")

    if not withdraw:
        raise HTTPException(status_code=404, detail="Withdraw not found")

    response = withdraw_response(withdraw)
    response["message"] = "Withdraw rad etildi, pul balansga qaytarildi"
    return response
