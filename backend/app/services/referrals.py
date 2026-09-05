from decimal import Decimal
import secrets

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import config
from app.models.order import Order
from app.models.referral import Referral, ReferralProfile, ReferralReward


REGISTRATION_BONUS = Decimal("0")
FIRST_SHOP_BONUS = Decimal("0")


def _new_referral_code(db: Session) -> str:
    for _ in range(32):
        code = secrets.token_urlsafe(9)
        if not db.query(ReferralProfile.telegram_id).filter(
            ReferralProfile.referral_code == code
        ).first():
            return code
    raise RuntimeError("Unique referral code could not be generated")


def ensure_referral_profile(db: Session, telegram_id: int) -> ReferralProfile:
    profile = db.get(ReferralProfile, telegram_id)
    if profile:
        return profile
    profile = ReferralProfile(
        telegram_id=telegram_id,
        referral_code=_new_referral_code(db),
    )
    db.add(profile)
    db.flush()
    return profile


def attach_registration_referral(
    db: Session,
    referred_telegram_id: int,
    referral_code: str | None,
) -> Referral | None:
    if not config.REFERRALS_ENABLED:
        return None
    code = (referral_code or "").strip()
    if not code:
        return None
    referrer = (
        db.query(ReferralProfile)
        .filter(ReferralProfile.referral_code == code)
        .with_for_update()
        .first()
    )
    if not referrer or referrer.telegram_id == referred_telegram_id:
        return None
    if db.query(Referral.id).filter(
        Referral.referred_telegram_id == referred_telegram_id
    ).first():
        return None
    referral = Referral(
        referrer_telegram_id=referrer.telegram_id,
        referred_telegram_id=referred_telegram_id,
        status="ACTIVE",
    )
    db.add(referral)
    db.flush()
    from app.services.arena_v5_seasons import award_active_arena_referral_points

    award_active_arena_referral_points(db, referral)
    return referral


def award_first_shop_bonus(db: Session, referred_telegram_id: int) -> bool:
    del db, referred_telegram_id
    return False


def referral_summary(db: Session, telegram_id: int) -> dict:
    profile = ensure_referral_profile(db, telegram_id)
    total_referrals = db.query(func.count(Referral.id)).filter(
        Referral.referrer_telegram_id == telegram_id,
        Referral.status == "ACTIVE",
    ).scalar() or 0
    shop_buyers = db.query(func.count(Referral.id)).filter(
        Referral.referrer_telegram_id == telegram_id,
        Referral.status == "ACTIVE",
        db.query(Order.id).filter(
            Order.telegram_id == Referral.referred_telegram_id,
            Order.status == "COMPLETED",
        ).exists(),
    ).scalar() or 0
    total_earned = db.query(func.coalesce(func.sum(ReferralReward.amount), 0)).filter(
        ReferralReward.beneficiary_telegram_id == telegram_id,
        ReferralReward.status == "AWARDED",
    ).scalar()
    return {
        "profile": profile,
        "total_referrals": int(total_referrals),
        "coin_shop_buyers": int(shop_buyers),
        "total_earned_uzs": Decimal(str(total_earned)),
    }
