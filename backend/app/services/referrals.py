from decimal import Decimal
import secrets

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.crud.transaction import create_transaction
from app.crud.wallet import get_wallet_for_update
from app.models.order import Order
from app.models.referral import Referral, ReferralProfile, ReferralReward


REGISTRATION_BONUS = Decimal("1000")
FIRST_SHOP_BONUS = Decimal("5000")
REGISTRATION_REWARD = "REGISTRATION"
FIRST_SHOP_REWARD = "FIRST_SHOP_COMPLETION"


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


def _credit_reward(
    db: Session,
    referral: Referral,
    reward_type: str,
    amount: Decimal,
) -> ReferralReward:
    wallet = get_wallet_for_update(db, referral.referrer_telegram_id)
    if not wallet:
        raise RuntimeError("Referrer wallet not found")
    before = Decimal(str(wallet.uzs_balance))
    wallet.uzs_balance = before + amount
    transaction = create_transaction(
        db=db,
        telegram_id=referral.referrer_telegram_id,
        currency="UZS",
        amount=amount,
        balance_before=before,
        balance_after=wallet.uzs_balance,
        type=(
            "REFERRAL_REGISTRATION_BONUS"
            if reward_type == REGISTRATION_REWARD
            else "REFERRAL_FIRST_SHOP_BONUS"
        ),
        description=f"Referral reward #{referral.id}",
        commit=False,
    )
    reward = ReferralReward(
        referral_id=referral.id,
        beneficiary_telegram_id=referral.referrer_telegram_id,
        reward_type=reward_type,
        amount=amount,
        transaction_id=transaction.id,
        status="AWARDED",
    )
    db.add(reward)
    db.flush()
    return reward


def attach_registration_referral(
    db: Session,
    referred_telegram_id: int,
    referral_code: str | None,
) -> Referral | None:
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
    _credit_reward(db, referral, REGISTRATION_REWARD, REGISTRATION_BONUS)
    return referral


def award_first_shop_bonus(db: Session, referred_telegram_id: int) -> bool:
    referral = (
        db.query(Referral)
        .filter(
            Referral.referred_telegram_id == referred_telegram_id,
            Referral.status == "ACTIVE",
        )
        .with_for_update()
        .first()
    )
    if not referral:
        return False
    if db.query(ReferralReward.id).filter(
        ReferralReward.referral_id == referral.id,
        ReferralReward.reward_type == FIRST_SHOP_REWARD,
    ).first():
        return False
    _credit_reward(db, referral, FIRST_SHOP_REWARD, FIRST_SHOP_BONUS)
    return True


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
