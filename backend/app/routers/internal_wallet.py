import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import INTERNAL_API_KEY
from app.core.database import get_db
from app.crud.user import get_user
from app.crud.wallet import get_wallet


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
