from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.schemas.user import InternalUserRegister
from app.services.internal_users import (
    InternalUserServiceError,
    mark_internal_user_seen,
    register_internal_user,
)

router = APIRouter(
    prefix="/user",
    tags=["User"],
)


@router.post("/register")
def register(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        result = register_internal_user(
            db,
            InternalUserRegister(
                telegram_id=current_user.telegram_id,
                username=current_user.username,
                first_name=current_user.first_name,
            ),
        )
    except InternalUserServiceError:
        raise HTTPException(500, "User registration failed")

    return {
        "success": True,
        "message": "User created successfully" if result.created else "User already exists",
        "telegram_id": current_user.telegram_id,
    }


@router.post("/seen")
def user_seen(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        updated = mark_internal_user_seen(db, current_user.telegram_id)
    except InternalUserServiceError:
        raise HTTPException(500, "User activity update failed")
    if not updated:
        raise HTTPException(404, "User not found")

    return {
        "success": True,
        "message": "User last seen updated",
        "telegram_id": user.telegram_id,
    }
