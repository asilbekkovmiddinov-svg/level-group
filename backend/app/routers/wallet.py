from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.crud.wallet import get_wallet
from app.schemas.wallet import AddEFC
from app.routers.internal_wallet import require_internal_api_key
from app.services.wallet_service import (
    InvalidWalletAmountError,
    WalletOperationFailedError,
    add_efc_with_transaction,
)

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
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    try:
        updated_wallet = add_efc_with_transaction(
            db=db,
            telegram_id=data.telegram_id,
            amount=data.amount,
            transaction_type="ADMIN_ADD_EFC",
            description="Admin tomonidan EFC qo‘shildi",
        )
    except InvalidWalletAmountError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))
    except WalletOperationFailedError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))

    return {
        "message": "EFC added successfully",
        "telegram_id": data.telegram_id,
        "amount": float(data.amount),
        "balance_before": float(updated_wallet.efc_balance - data.amount),
        "balance_after": float(updated_wallet.efc_balance),
    }
