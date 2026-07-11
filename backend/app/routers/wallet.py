from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import INTERNAL_API_KEY
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.crud.wallet import get_wallet, get_or_create_wallet, add_efc
from app.crud.transaction import create_transaction
from app.schemas.wallet import AddEFC

router = APIRouter(
    prefix="/wallet",
    tags=["Wallet"],
)


@router.get("")
def wallet_info(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    wallet = get_wallet(db, current_user.telegram_id)

    if not wallet:
        return {"message": "Wallet not found"}

    return {
        "telegram_id": wallet.telegram_id,
        "efc_balance": float(wallet.efc_balance),
        "uzs_balance": float(wallet.uzs_balance),
        "locked_efc": float(wallet.locked_efc),
        "locked_uzs": float(wallet.locked_uzs),
    }


@router.post("/add-efc", include_in_schema=False)
def add_efc_balance(
    data: AddEFC,
    x_internal_api_key: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
):
    if not INTERNAL_API_KEY or not x_internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal wallet operations are not configured",
        )

    if x_internal_api_key != INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal wallet operation is forbidden",
        )

    wallet = get_or_create_wallet(db, data.telegram_id)
    balance_before = wallet.efc_balance

    updated_wallet = add_efc(
        db=db,
        telegram_id=data.telegram_id,
        amount=data.amount,
    )

    if not updated_wallet:
        return {"message": "Wallet not found"}

    balance_after = updated_wallet.efc_balance

    create_transaction(
        db=db,
        telegram_id=data.telegram_id,
        currency="EFC",
        amount=data.amount,
        balance_before=balance_before,
        balance_after=balance_after,
        type="ADMIN_ADD_EFC",
        description="Admin tomonidan EFC qo‘shildi",
    )

    return {
        "message": "EFC added successfully",
        "telegram_id": data.telegram_id,
        "amount": float(data.amount),
        "balance_before": float(balance_before),
        "balance_after": float(balance_after),
    }
