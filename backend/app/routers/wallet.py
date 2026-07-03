from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.wallet import get_wallet, add_efc
from app.crud.transaction import create_transaction
from app.schemas.wallet import AddEFC

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


@router.post("/add-efc")
def add_efc_balance(
    data: AddEFC,
    db: Session = Depends(get_db)
):
    result = add_efc(db, data.telegram_id, data.amount)

    if not result:
        return {
            "message": "Wallet not found"
        }

    before, after = result

    create_transaction(
        db=db,
        telegram_id=data.telegram_id,
        currency="EFC",
        amount=data.amount,
        balance_before=before,
        balance_after=after,
        type="ADMIN_ADD_EFC",
        description="EFC added manually"
    )

    return {
        "message": "EFC added successfully",
        "telegram_id": data.telegram_id,
        "balance_before": float(before
