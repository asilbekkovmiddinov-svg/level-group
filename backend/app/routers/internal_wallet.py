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
    db: Session = Depends(get_db),
):
    deposit = create_deposit(db, data, data.telegram_id)
    if deposit == "invalid_amount":
        raise HTTPException(status_code=400, detail="Deposit amount must be greater than zero")
    if deposit == "minimum_amount":
        raise HTTPException(status_code=400, detail="Minimal deposit summasi 15 000 UZS")
    return {"message": "Deposit request created", "deposit_id": deposit.id, "telegram_id": deposit.telegram_id, "amount": float(deposit.amount), "status": deposit.status}
