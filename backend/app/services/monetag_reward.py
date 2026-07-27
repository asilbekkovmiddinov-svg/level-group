from datetime import timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core.config import MONETAG_REWARD_SESSION_TTL_SECONDS
from app.crud import wheel
from app.models.user import User
from app.models.wheel import AdsgramRewardSession, MonetagRewardEvent, WheelDailyLimit
from app.services import adsgram_reward
from app.services.arena_time import utc_now


PENDING = "PENDING"
CLAIMED = "CLAIMED"
REJECTED = "REJECTED"
EXPIRED = "EXPIRED"
SOURCE = "wheel_reward"


def _lock_reward_eligibility(db: Session, telegram_id: int, now) -> None:
    db.query(User).filter(User.telegram_id == telegram_id).with_for_update().one()
    limit = (
        db.query(WheelDailyLimit)
        .filter(
            WheelDailyLimit.telegram_id == telegram_id,
            WheelDailyLimit.spin_date == wheel.get_today(),
        )
        .with_for_update()
        .one_or_none()
    )
    if not limit:
        limit = WheelDailyLimit(
            telegram_id=telegram_id,
            spin_date=wheel.get_today(),
            free_spin_used=False,
            ad_spin_count=0,
            bonus_spin_count=0,
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
    if int(limit.rewarded_ad_spins or 0) > 0:
        raise ValueError("Foydalanilmagan reklama spini mavjud")


def create_reward_session(db: Session, telegram_id: int, ymid: str) -> MonetagRewardEvent:
    now = utc_now()
    _lock_reward_eligibility(db, telegram_id, now)
    if db.query(MonetagRewardEvent).filter(MonetagRewardEvent.ymid == ymid).first():
        raise ValueError("YMID allaqachon ishlatilgan")

    active_monetag = (
        db.query(MonetagRewardEvent)
        .filter(
            MonetagRewardEvent.telegram_id == telegram_id,
            MonetagRewardEvent.status == PENDING,
        )
        .with_for_update()
        .all()
    )
    for session in active_monetag:
        if session.expires_at > now:
            raise ValueError("Reklama sessiyasi allaqachon ochilgan")
        session.status = EXPIRED

    active_adsgram = (
        db.query(AdsgramRewardSession)
        .filter(
            AdsgramRewardSession.telegram_id == telegram_id,
            AdsgramRewardSession.status.in_((adsgram_reward.PENDING, adsgram_reward.VERIFIED)),
            AdsgramRewardSession.expires_at > now,
        )
        .with_for_update()
        .first()
    )
    if active_adsgram:
        raise ValueError("Reklama sessiyasi allaqachon ochilgan")

    session = MonetagRewardEvent(
        ymid=ymid,
        telegram_id=telegram_id,
        status=PENDING,
        source=SOURCE,
        expires_at=now + timedelta(seconds=MONETAG_REWARD_SESSION_TTL_SECONDS),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def process_postback(
    db: Session,
    *,
    ymid: str,
    telegram_id: int,
    event: str,
    value: str,
    zone: str | None,
    sub: str | None,
    price: str | None,
    source: str,
) -> tuple[MonetagRewardEvent | None, bool]:
    now = utc_now()
    session = (
        db.query(MonetagRewardEvent)
        .filter(MonetagRewardEvent.ymid == ymid)
        .with_for_update()
        .first()
    )
    if not session:
        db.rollback()
        return None, False
    if session.status == CLAIMED:
        db.rollback()
        return session, False
    if session.status != PENDING or session.expires_at <= now:
        if session.status == PENDING:
            session.status = EXPIRED
            db.commit()
        else:
            db.rollback()
        return session, False

    matches = (
        event == "impression"
        and value == "valued"
        and source == SOURCE
        and session.source == SOURCE
        and session.telegram_id == telegram_id
    )
    session.event = event
    session.reward_type = value
    session.zone_id = zone
    session.sub_zone_id = sub
    try:
        session.estimated_price = Decimal(price) if price not in (None, "") else None
    except InvalidOperation:
        session.estimated_price = None

    if not matches:
        session.status = REJECTED
        db.commit()
        return session, False

    adsgram_reward.grant_rewarded_spin(db, telegram_id, now=now)
    session.status = CLAIMED
    session.claimed_at = now
    db.commit()
    db.refresh(session)
    return session, True


def get_reward_status(db: Session, telegram_id: int, ymid: str) -> MonetagRewardEvent | None:
    session = (
        db.query(MonetagRewardEvent)
        .filter(
            MonetagRewardEvent.ymid == ymid,
            MonetagRewardEvent.telegram_id == telegram_id,
        )
        .first()
    )
    if session and session.status == PENDING and session.expires_at <= utc_now():
        session.status = EXPIRED
        db.commit()
        db.refresh(session)
    return session
