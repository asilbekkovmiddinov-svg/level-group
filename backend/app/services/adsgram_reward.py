import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core import config
from app.core.config import ADSGRAM_REWARD_SESSION_TTL_SECONDS
from app.crud import wheel
from app.models.user import User
from app.models.wall_rush import GameTicketWallet
from app.models.wheel import AdsgramRewardSession, WheelDailyLimit
from app.services.arena_time import utc_now
from app.services.wall_rush import (
    WALL_RUSH_AD_COOLDOWN,
    WallRushError,
    get_wallet,
    grant_ad_ticket,
)
from app.services.penalty_duel_ads import (
    PENALTY_DUEL_AD_COOLDOWN,
    PenaltyDuelAdError,
    grant_penalty_duel_ad_ticket,
)


PENDING = "PENDING"
VERIFIED = "VERIFIED"
CLAIMED = "CLAIMED"
EXPIRED = "EXPIRED"
WHEEL_PURPOSE = "WHEEL"
WALL_RUSH_PURPOSE = "WALL_RUSH"
PENALTY_DUEL_PURPOSE = "PENALTY_DUEL"
PENALTY_DUEL_TADS_PURPOSE = "PENALTY_DUEL_TADS"
PENALTY_DUEL_TELEGA_PURPOSE = "PENALTY_DUEL_TELEGA"
PENALTY_DUEL_ONCLICKA_PURPOSE = "PENALTY_DUEL_ONCLICKA"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _expire_or_reject_open_sessions(
    db: Session, telegram_id: int, now,
) -> None:
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
        if _as_utc(session.expires_at) > _as_utc(now):
            raise ValueError("Reklama sessiyasi allaqachon ochilgan")
        session.status = EXPIRED


def _new_session(
    db: Session, telegram_id: int, purpose: str, now,
) -> tuple[AdsgramRewardSession, str]:
    _expire_or_reject_open_sessions(db, telegram_id, now)
    token = secrets.token_urlsafe(32)
    session = AdsgramRewardSession(
        telegram_id=telegram_id,
        token_hash=_token_hash(token),
        purpose=purpose,
        status=PENDING,
        expires_at=now + timedelta(seconds=ADSGRAM_REWARD_SESSION_TTL_SECONDS),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, token


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

    return _new_session(db, telegram_id, WHEEL_PURPOSE, now)


def create_wall_rush_reward_session(
    db: Session, telegram_id: int,
) -> tuple[AdsgramRewardSession, str]:
    now = utc_now()
    db.query(User).filter(User.telegram_id == telegram_id).with_for_update().one()
    wallet = get_wallet(db, telegram_id, lock=True)
    last = wallet.last_rewarded_ad_at
    if last is not None:
        if _as_utc(now) < _as_utc(last) + WALL_RUSH_AD_COOLDOWN:
            raise ValueError("Rewarded reklama cooldown faol")
    return _new_session(db, telegram_id, WALL_RUSH_PURPOSE, now)


def create_penalty_duel_reward_session(
    db: Session, telegram_id: int,
) -> tuple[AdsgramRewardSession, str]:
    now = utc_now()
    db.query(User).filter(User.telegram_id == telegram_id).with_for_update().one()
    wallet = get_wallet(db, telegram_id, lock=True)
    last = wallet.last_penalty_duel_rewarded_ad_at
    if last is not None:
        if _as_utc(now) < _as_utc(last) + PENALTY_DUEL_AD_COOLDOWN:
            raise ValueError("Penalty Duel reklama cooldown faol")
    return _new_session(db, telegram_id, PENALTY_DUEL_PURPOSE, now)


def create_onclicka_penalty_duel_reward_session(
    db: Session, telegram_id: int,
) -> tuple[AdsgramRewardSession, str]:
    """Open a short-lived server-authoritative OnClickA view session."""
    if not config.onclicka_rewarded_ad_ready():
        raise ValueError("OnClickA rewarded ads are disabled")
    now = utc_now()
    db.query(User).filter(User.telegram_id == telegram_id).with_for_update().one()
    wallet = get_wallet(db, telegram_id, lock=True)
    last = wallet.last_penalty_duel_rewarded_ad_at
    if last is not None:
        if _as_utc(now) < _as_utc(last) + PENALTY_DUEL_AD_COOLDOWN:
            raise ValueError("Penalty Duel reklama cooldown faol")
    return _new_session(db, telegram_id, PENALTY_DUEL_ONCLICKA_PURPOSE, now)


def create_tads_penalty_duel_reward_session(
    db: Session, telegram_id: int,
) -> tuple[AdsgramRewardSession, str]:
    """Open a server-authoritative session before showing a TADS video."""
    if not config.penalty_duel_tads_ready():
        raise ValueError("TADS rewarded ads are disabled")
    now = utc_now()
    db.query(User).filter(User.telegram_id == telegram_id).with_for_update().one()
    wallet = get_wallet(db, telegram_id, lock=True)
    last = wallet.last_penalty_duel_rewarded_ad_at
    if last is not None:
        if _as_utc(now) < _as_utc(last) + PENALTY_DUEL_AD_COOLDOWN:
            raise ValueError("Penalty Duel reklama cooldown faol")
    return _new_session(db, telegram_id, PENALTY_DUEL_TADS_PURPOSE, now)


def create_telega_penalty_duel_reward_session(
    db: Session, telegram_id: int,
) -> tuple[AdsgramRewardSession, str]:
    """Open a server-authoritative session before showing a Telega.io ad."""
    if not config.penalty_duel_telega_ready():
        raise ValueError("Telega.io rewarded ads are disabled")
    now = utc_now()
    db.query(User).filter(User.telegram_id == telegram_id).with_for_update().one()
    wallet = get_wallet(db, telegram_id, lock=True)
    last = wallet.last_penalty_duel_rewarded_ad_at
    if last is not None:
        if _as_utc(now) < _as_utc(last) + PENALTY_DUEL_AD_COOLDOWN:
            raise ValueError("Penalty Duel reklama cooldown faol")
    return _new_session(db, telegram_id, PENALTY_DUEL_TELEGA_PURPOSE, now)


def verify_adsgram_callback(db: Session, telegram_id: int) -> AdsgramRewardSession | None:
    now = utc_now()
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.status == PENDING,
            AdsgramRewardSession.purpose.in_((
                WHEEL_PURPOSE, WALL_RUSH_PURPOSE, PENALTY_DUEL_PURPOSE,
            )),
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


def _claimable_session(
    db: Session, telegram_id: int, token: str, purpose: str,
) -> tuple[AdsgramRewardSession, datetime]:
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
    if session.purpose != purpose:
        raise ValueError("Reward sessiyasi bu o‘yin uchun yaratilmagan")
    if session.status == CLAIMED:
        raise ValueError("Reward allaqachon olingan")
    if _as_utc(session.expires_at) <= _as_utc(now):
        session.status = EXPIRED
        db.commit()
        raise ValueError("Reward sessiyasi eskirgan")
    if session.status != VERIFIED:
        raise ValueError("Adsgram tasdig‘i hali kelmadi")
    return session, now


def claim_reward(db: Session, telegram_id: int, token: str) -> AdsgramRewardSession:
    session, now = _claimable_session(db, telegram_id, token, WHEEL_PURPOSE)

    grant_rewarded_spin(db, telegram_id, now=now)
    session.status = CLAIMED
    session.claimed_at = now
    db.commit()
    db.refresh(session)
    return session


def claim_wall_rush_reward(
    db: Session, telegram_id: int, token: str,
) -> tuple[AdsgramRewardSession, GameTicketWallet]:
    session, now = _claimable_session(db, telegram_id, token, WALL_RUSH_PURPOSE)
    try:
        wallet = grant_ad_ticket(
            db, telegram_id, f"adsgram:session:{session.id}", now=now,
        )
    except WallRushError as error:
        raise ValueError(str(error)) from error
    session.status = CLAIMED
    session.claimed_at = now
    db.commit()
    db.refresh(session)
    return session, wallet


def claim_penalty_duel_reward(
    db: Session, telegram_id: int, token: str,
) -> tuple[AdsgramRewardSession, GameTicketWallet]:
    session, now = _claimable_session(db, telegram_id, token, PENALTY_DUEL_PURPOSE)
    try:
        wallet = grant_penalty_duel_ad_ticket(
            db,
            telegram_id,
            "ADSGRAM",
            f"session:{session.id}",
            now=now,
        )
    except PenaltyDuelAdError as error:
        raise ValueError(str(error)) from error
    session.status = CLAIMED
    session.claimed_at = now
    db.commit()
    db.refresh(session)
    return session, wallet


def complete_onclicka_penalty_duel_reward(
    db: Session, telegram_id: int,
) -> tuple[AdsgramRewardSession, GameTicketWallet] | None:
    """Atomically settle the newest pending OnClickA session exactly once."""
    now = utc_now()
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.purpose == PENALTY_DUEL_ONCLICKA_PURPOSE,
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
    try:
        wallet = grant_penalty_duel_ad_ticket(
            db,
            telegram_id,
            "ONCLICKA",
            f"session:{session.id}",
            now=now,
            commit=False,
        )
    except PenaltyDuelAdError:
        session.status = EXPIRED
        db.commit()
        raise
    session.status = CLAIMED
    session.verified_at = now
    session.claimed_at = now
    db.commit()
    db.refresh(session)
    db.refresh(wallet)
    return session, wallet


def complete_tads_penalty_duel_reward(
    db: Session, telegram_id: int,
) -> tuple[AdsgramRewardSession, GameTicketWallet] | None:
    """Atomically settle the newest pending TADS session exactly once."""
    now = utc_now()
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.purpose == PENALTY_DUEL_TADS_PURPOSE,
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
    try:
        wallet = grant_penalty_duel_ad_ticket(
            db,
            telegram_id,
            "TADS",
            f"session:{session.id}",
            now=now,
            commit=False,
        )
    except PenaltyDuelAdError:
        session.status = EXPIRED
        db.commit()
        raise
    session.status = CLAIMED
    session.verified_at = now
    session.claimed_at = now
    db.commit()
    db.refresh(session)
    db.refresh(wallet)
    return session, wallet


def has_recent_tads_penalty_duel_reward(db: Session, telegram_id: int) -> bool:
    """Absorb duplicate callbacks when Penalty and Wall Rush share a TADS widget."""
    now = utc_now()
    return db.query(AdsgramRewardSession.id).filter(
        AdsgramRewardSession.telegram_id == telegram_id,
        AdsgramRewardSession.purpose == PENALTY_DUEL_TADS_PURPOSE,
        AdsgramRewardSession.status == CLAIMED,
        AdsgramRewardSession.expires_at > now,
    ).first() is not None


def complete_telega_penalty_duel_reward(
    db: Session, telegram_id: int,
) -> tuple[AdsgramRewardSession, GameTicketWallet] | None:
    """Settle one pending Telega.io session without requiring an event id."""
    now = utc_now()
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.purpose == PENALTY_DUEL_TELEGA_PURPOSE,
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
    try:
        wallet = grant_penalty_duel_ad_ticket(
            db,
            telegram_id,
            "TELEGA",
            f"session:{session.id}",
            now=now,
            commit=False,
        )
    except PenaltyDuelAdError:
        session.status = EXPIRED
        db.commit()
        raise
    session.status = CLAIMED
    session.verified_at = now
    session.claimed_at = now
    db.commit()
    db.refresh(session)
    db.refresh(wallet)
    return session, wallet


def has_recent_telega_penalty_duel_reward(db: Session, telegram_id: int) -> bool:
    now = utc_now()
    return db.query(AdsgramRewardSession.id).filter(
        AdsgramRewardSession.telegram_id == telegram_id,
        AdsgramRewardSession.purpose == PENALTY_DUEL_TELEGA_PURPOSE,
        AdsgramRewardSession.status == CLAIMED,
        AdsgramRewardSession.expires_at > now,
    ).first() is not None


def cancel_wall_rush_reward_session(
    db: Session, telegram_id: int, token: str,
) -> AdsgramRewardSession:
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.token_hash == _token_hash(token),
            AdsgramRewardSession.purpose == WALL_RUSH_PURPOSE,
        )
        .with_for_update()
        .first()
    )
    if not session:
        raise ValueError("Reward sessiyasi topilmadi")
    if session.status == PENDING:
        session.status = EXPIRED
        db.commit()
        db.refresh(session)
    return session


def cancel_penalty_duel_reward_session(
    db: Session, telegram_id: int, token: str,
) -> AdsgramRewardSession:
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.token_hash == _token_hash(token),
            AdsgramRewardSession.purpose == PENALTY_DUEL_PURPOSE,
        )
        .with_for_update()
        .first()
    )
    if not session:
        raise ValueError("Reward sessiyasi topilmadi")
    if session.status == PENDING:
        session.status = EXPIRED
        db.commit()
        db.refresh(session)
    return session


def cancel_onclicka_penalty_duel_reward_session(
    db: Session, telegram_id: int, token: str,
) -> AdsgramRewardSession:
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.token_hash == _token_hash(token),
            AdsgramRewardSession.purpose == PENALTY_DUEL_ONCLICKA_PURPOSE,
        )
        .with_for_update()
        .first()
    )
    if not session:
        raise ValueError("Reward sessiyasi topilmadi")
    if session.status == PENDING:
        session.status = EXPIRED
        db.commit()
        db.refresh(session)
    return session


def cancel_tads_penalty_duel_reward_session(
    db: Session, telegram_id: int, token: str,
) -> AdsgramRewardSession:
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.token_hash == _token_hash(token),
            AdsgramRewardSession.purpose == PENALTY_DUEL_TADS_PURPOSE,
        )
        .with_for_update()
        .first()
    )
    if not session:
        raise ValueError("Reward sessiyasi topilmadi")
    if session.status == PENDING:
        session.status = EXPIRED
        db.commit()
        db.refresh(session)
    return session


def cancel_telega_penalty_duel_reward_session(
    db: Session, telegram_id: int, token: str,
) -> AdsgramRewardSession:
    session = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.token_hash == _token_hash(token),
            AdsgramRewardSession.purpose == PENALTY_DUEL_TELEGA_PURPOSE,
        )
        .with_for_update()
        .first()
    )
    if not session:
        raise ValueError("Reward sessiyasi topilmadi")
    if session.status == PENDING:
        session.status = EXPIRED
        db.commit()
        db.refresh(session)
    return session
