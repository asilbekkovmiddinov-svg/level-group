from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.user import User
from app.core.telegram_auth import TelegramUser


def get_user(db: Session, telegram_id: int):
    return db.query(User).filter(
        User.telegram_id == telegram_id
    ).first()


def create_user(db: Session, user: TelegramUser):
    db_user = User(
        telegram_id=user.telegram_id,
        first_name=user.first_name,
        username=user.username,
        language=user.language,
        last_seen_at=datetime.now(timezone.utc),
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


def update_user_last_seen(db: Session, telegram_id: int):
    user = get_user(db=db, telegram_id=telegram_id)

    if not user:
        return None

    user.last_seen_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(user)

    return user
