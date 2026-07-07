from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.user import (
    get_user,
    create_user,
    update_user_last_seen,
)
from app.crud.wallet import create_wallet
from app.schemas.user import UserCreate

router = APIRouter(
    prefix="/user",
    tags=["User"],
)


@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = get_user(db, user.telegram_id)

    if db_user:
        update_user_last_seen(db=db, telegram_id=user.telegram_id)

        return {
            "success": True,
            "message": "User already exists",
            "telegram_id": db_user.telegram_id,
        }

    db_user = create_user(db, user)
    create_wallet(db, user.telegram_id)

    return {
        "success": True,
        "message": "User created successfully",
        "telegram_id": db_user.telegram_id,
    }


@router.post("/{telegram_id}/seen")
def user_seen(
    telegram_id: int,
    db: Session = Depends(get_db),
):
    user = update_user_last_seen(
        db=db,
        telegram_id=telegram_id,
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
