from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user import UserCreate


def get_user(db: Session, telegram_id: int):
    return db.query(User).filter(
        User.telegram_id == telegram_id
    ).first()


def create_user(db: Session, user: UserCreate):
    db_user = User(
        telegram_id=user.telegram_id,
        first_name=user.first_name,
        username=user.username,
        language=user.language
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user
