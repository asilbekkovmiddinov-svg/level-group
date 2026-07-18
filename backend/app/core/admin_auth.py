from fastapi import Depends, HTTPException, status

from app.core.config import ADMIN_TELEGRAM_IDS
from app.core.telegram_auth import TelegramUser, get_current_telegram_user


def require_promotions_admin(
    current_user: TelegramUser = Depends(get_current_telegram_user),
) -> TelegramUser:
    """Return the verified Telegram user only when it is an allowed admin."""
    if current_user.telegram_id not in ADMIN_TELEGRAM_IDS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Promotions admin access is forbidden",
        )
    return current_user
