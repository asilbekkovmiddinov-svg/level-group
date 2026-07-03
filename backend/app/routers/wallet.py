from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.wallet import get_wallet

router = APIRouter(
    prefix="/wallet",
    tags=["Wallet"]
)


@router.get("/{telegram_id}")
def wallet_info(
    telegram_id: int,
    db: Session = Depends(get_db)
):
    wallet = get_wallet(db, telegram_id)

    if not wallet:
        return {
            "message": "Wallet not found"
        }

    return {
        "telegram_id": wallet.telegram_id,
        "efc_balance": float(wallet.efc_balance),
        "uzs_balance": float(wallet.uzs_balance),
        "locked_efc": float(wallet.locked_efc),
        "locked_uzs": float(wallet.locked_uzs)
    }
