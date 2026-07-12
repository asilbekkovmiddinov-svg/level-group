from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.crud.wallet import ZERO, get_wallet_for_update
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.user import InternalUserRegister


class InternalUserServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class InternalUserRegisterResult:
    telegram_id: int
    created: bool
    wallet_created: bool


def _locked_user(db: Session, telegram_id: int) -> User | None:
    return (
        db.query(User)
        .filter(User.telegram_id == telegram_id)
        .with_for_update()
        .first()
    )


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _update_profile(user: User, data: InternalUserRegister, now: datetime) -> None:
    username = _non_empty(data.username)
    first_name = _non_empty(data.first_name)
    last_name = _non_empty(data.last_name)
    if username is not None:
        user.username = username
    if first_name is not None:
        user.first_name = first_name
    if last_name is not None:
        user.last_name = last_name
    user.last_seen_at = now


def _ensure_wallet(db: Session, telegram_id: int) -> bool:
    wallet = get_wallet_for_update(db, telegram_id)
    if wallet:
        return False
    db.add(
        Wallet(
            telegram_id=telegram_id,
            efc_balance=ZERO,
            uzs_balance=ZERO,
            locked_efc=ZERO,
            locked_uzs=ZERO,
        )
    )
    db.flush()
    return True


def _register_existing_user(
    db: Session, data: InternalUserRegister, now: datetime
) -> InternalUserRegisterResult:
    try:
        user = _locked_user(db, data.telegram_id)
        if not user:
            raise InternalUserServiceError("User registration conflict")
        _update_profile(user, data, now)
        wallet_created = _ensure_wallet(db, data.telegram_id)
        db.commit()
        return InternalUserRegisterResult(data.telegram_id, False, wallet_created)
    except InternalUserServiceError:
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise InternalUserServiceError("Internal user registration failed") from error


def register_internal_user(
    db: Session, data: InternalUserRegister, now: datetime | None = None
) -> InternalUserRegisterResult:
    now = now or datetime.now(timezone.utc)
    try:
        user = _locked_user(db, data.telegram_id)
        if user:
            _update_profile(user, data, now)
            wallet_created = _ensure_wallet(db, data.telegram_id)
            db.commit()
            return InternalUserRegisterResult(data.telegram_id, False, wallet_created)

        user = User(
            telegram_id=data.telegram_id,
            username=_non_empty(data.username),
            first_name=_non_empty(data.first_name) or "Telegram user",
            last_name=_non_empty(data.last_name),
            language="uz",
            last_seen_at=now,
        )
        db.add(user)
        db.flush()
        wallet_created = _ensure_wallet(db, data.telegram_id)
        db.commit()
        return InternalUserRegisterResult(data.telegram_id, True, wallet_created)
    except IntegrityError:
        db.rollback()
        return _register_existing_user(db, data, now)
    except SQLAlchemyError as error:
        db.rollback()
        raise InternalUserServiceError("Internal user registration failed") from error


def mark_internal_user_seen(
    db: Session, telegram_id: int, now: datetime | None = None
) -> bool:
    try:
        user = _locked_user(db, telegram_id)
        if not user:
            db.rollback()
            return False
        user.last_seen_at = now or datetime.now(timezone.utc)
        db.commit()
        return True
    except SQLAlchemyError as error:
        db.rollback()
        raise InternalUserServiceError("Internal user activity update failed") from error
