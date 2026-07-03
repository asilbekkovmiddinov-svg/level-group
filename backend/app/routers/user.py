from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.user import get_user, create_user
from app.crud.wallet import create_wallet
from app.schemas.user import UserCreate

router = APIRouter(
    prefix="/user",
    tags=["User"]
)


@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = get_user(db, user.telegram_id)

    if db_user:
        return {
            "message": "User already exists"
        }

    db_user = create_user(db, user)
    create_wallet(db, user.telegram_id)

    return {
        "message": "User created successfully",
        "telegram_id": db_user.telegram_id
    }
