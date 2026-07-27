import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import ADSGRAM_REWARD_SESSION_TTL_SECONDS
from app.crud import wheel
from app.models.user import User
from app.models.wheel import AdsgramRewardSession, WheelDailyLimit
from app.services.arena_time import utc_now


PENDING = "PENDING"
VERIFIED = "VERIFIED"
CLAIMED = "CLAIMED"
EXPIRED = "EXPIRED"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_reward_session(db: Session, telegram_id: int) -> tuple[AdsgramRewardSession, str]:
    now = utc_now()
    db.query(User).filter(User.telegram_id == telegram_id).with_for_update().one()
    limit = (
        db.query(WheelDailyLimit)
        .filter(
            WheelDailyLimit.telegram_id == telegram_id,
            WheelDailyLimit.spin_date == wheel.get_today(),
        )
        .one_or_none()
    )
    if not limit:
        limit = WheelDailyLimit(
            telegram_id=telegram_id,
            spin_date=wheel.get_today(),
            free_spin_used=False,
            ad_spin_count=0,
            bonus_spin_count=0,
            last_ad_spin_at=None,
            rewarded_ad_spins=0,
        )
        db.add(limit)
        db.flush()
    available, next_at, _ = wheel.get_cooldown_status(
        limit.last_ad_spin_at,
        timedelta(minutes=wheel.AD_COOLDOWN_MINUTES),
        now,
    )
    if not available:
        raise ValueError(f"Keyingi reklama: {next_at}")
    if int(getattr(limit, "rewarded_ad_spins", 0) or 0) > 0:
        raise ValueError("Foydalanilmagan reklama spini mavjud")

    pending = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.status.in_((PENDING, VERIFIED)),
        )
        .with_for_update()
        .all()
    )
    for session in pending:
        if session.expires_at > now:
            raise ValueError("Reklama sessiyasi allaqachon ochilgan")
        session.status = EXPIRED

    token = secrets.token_urlsafe(32)
    session = AdsgramRewardSession(
        telegram_id=telegram_id,
        token_hash=_token_hash(token),
        status=PENDING,
        expires_at=now + timedelta(seconds=ADSGRAM_REWARD_SESSION_TTL_SECONDS),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, token


def verify_adsgram_callback(db: Session, telegram_id: int) -> AdsgramRewardSession | None:
    now = utc_now()
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.status == PENDING,
            AdsgramRewardSession.expires_at > now,
        )
        .order_by(AdsgramRewardSession.created_at.desc(), AdsgramRewardSession.id.desc())
        .with_for_update()
        .first()
    )
    if not session:
        db.rollback()
        return None
    session.status = VERIFIED
    session.verified_at = now
    db.commit()
    db.refresh(session)
    return session


def spin_rewarded_ad(
    db: Session,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
):
    limit = (
        db.query(WheelDailyLimit)
        .filter(
            WheelDailyLimit.telegram_id == telegram_id,
            WheelDailyLimit.spin_date == wheel.get_today(),
        )
        .with_for_update()
        .one_or_none()
    )
    if not limit or int(limit.rewarded_ad_spins or 0) <= 0:
        return {"success": False, "message": "Avval rewarded reklamani oxirigacha ko‘ring"}
    return wheel.spin_wheel(
        db=db,
        telegram_id=telegram_id,
        spin_type=wheel.SPIN_TYPE_AD,
        username=username,
        first_name=first_name,
    )


def grant_rewarded_spin(
    db: Session,
    telegram_id: int,
    *,
    now=None,
) -> WheelDailyLimit:
    now = now or utc_now()
    limit = (
        db.query(WheelDailyLimit)
        .filter(
            WheelDailyLimit.telegram_id == telegram_id,
            WheelDailyLimit.spin_date == wheel.get_today(),
        )
        .with_for_update()
        .one()
    )
    available, _, _ = wheel.get_cooldown_status(
        limit.last_ad_spin_at,
        timedelta(minutes=wheel.AD_COOLDOWN_MINUTES),
        now,
    )
    if not available:
        raise ValueError("Rewarded reklama cooldown faol")
    if int(limit.rewarded_ad_spins or 0) > 0:
        raise ValueError("Foydalanilmagan reklama spini mavjud")
    limit.rewarded_ad_spins += 1
    limit.last_ad_spin_at = now
    return limit


def claim_reward(db: Session, telegram_id: int, token: str) -> AdsgramRewardSession:
    now = utc_now()
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.token_hash == _token_hash(token),
        )
        .with_for_update()
        .first()
    )
    if not session:
        raise ValueError("Reward sessiyasi topilmadi")
    if session.status == CLAIMED:
        raise ValueError("Reward allaqachon olingan")
    if session.expires_at <= now:
        session.status = EXPIRED
        db.commit()
        raise ValueError("Reward sessiyasi eskirgan")
    if session.status != VERIFIED:
        raise ValueError("Adsgram tasdig‘i hali kelmadi")

    grant_rewarded_spin(db, telegram_id, now=now)
    session.status = CLAIMED
    session.claimed_at = now
    db.commit()
    db.refresh(session)
    return session
