from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.crud.user import (
    get_user,
    create_user,
    update_user_last_seen,
)
from app.crud.wallet import create_wallet

router = APIRouter(
    prefix="/user",
    tags=["User"],
)


@router.post("/register")
def register(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    db_user = get_user(db, current_user.telegram_id)

    if db_user:
        update_user_last_seen(db=db, telegram_id=current_user.telegram_id)

        return {
            "success": True,
            "message": "User already exists",
            "telegram_id": db_user.telegram_id,
        }

    db_user = create_user(db, current_user)
    create_wallet(db, current_user.telegram_id)

    return {
        "success": True,
        "message": "User created successfully",
        "telegram_id": db_user.telegram_id,
    }


@router.post("/seen")
def user_seen(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    user = update_user_last_seen(
        db=db,
        telegram_id=current_user.telegram_id,
    )

    if not user:
        return {
            "success": False,
            "message": "User not found",
        }

    return {
        "success": True,
        "message": "User last seen updated",
        "telegram_id": user.telegram_id,
    }
