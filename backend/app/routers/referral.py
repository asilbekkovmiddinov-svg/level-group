from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import TELEGRAM_BOT_USERNAME
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.services.referrals import (
    FIRST_SHOP_BONUS,
    REGISTRATION_BONUS,
    referral_summary,
)


router = APIRouter(prefix="/referrals", tags=["Referrals"])


@router.get("/me")
def my_referrals(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    result = referral_summary(db, current_user.telegram_id)
    db.commit()
    profile = result["profile"]
    return {
        "success": True,
        "data": {
            "referral_code": profile.referral_code,
            "referral_link": (
                f"https://t.me/{TELEGRAM_BOT_USERNAME}"
                f"?start=ref_{profile.referral_code}"
            ),
            "total_referrals": result["total_referrals"],
            "coin_shop_buyers": result["coin_shop_buyers"],
            "total_earned_uzs": float(result["total_earned_uzs"]),
            "registration_bonus_uzs": float(REGISTRATION_BONUS),
            "first_shop_bonus_uzs": float(FIRST_SHOP_BONUS),
        },
    }
