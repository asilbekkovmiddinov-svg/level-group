from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.match import Match
from app.models.order import Order
from app.models.referral import Referral
from app.models.user import User
from app.models.wallet import Wallet
from app.models.wheel import WheelSpin
from app.schemas.campaign import CampaignExecutionRequest


def _active_users(db: Session):
    return db.query(User.telegram_id).filter(User.is_banned.is_(False))


def select_all_users(db: Session, _options: CampaignExecutionRequest) -> set[int]:
    return {row[0] for row in _active_users(db).all()}


def select_referral_users(db: Session, _options: CampaignExecutionRequest) -> set[int]:
    return {
        row[0]
        for row in _active_users(db)
        .join(Referral, Referral.referred_telegram_id == User.telegram_id)
        .filter(Referral.status == "ACTIVE", Referral.revoked_at.is_(None))
        .distinct().all()
    }


def select_coin_shop_users(db: Session, _options: CampaignExecutionRequest) -> set[int]:
    return {
        row[0]
        for row in _active_users(db)
        .join(Order, Order.telegram_id == User.telegram_id)
        .filter(Order.status == "COMPLETED").distinct().all()
    }


def select_arena_users(db: Session, _options: CampaignExecutionRequest) -> set[int]:
    return {
        row[0]
        for row in _active_users(db)
        .filter(or_(
            User.telegram_id.in_(db.query(Match.creator_telegram_id)),
            User.telegram_id.in_(db.query(Match.opponent_telegram_id).filter(Match.opponent_telegram_id.is_not(None))),
        )).all()
    }


def select_wheel_users(db: Session, _options: CampaignExecutionRequest) -> set[int]:
    return {
        row[0]
        for row in _active_users(db)
        .join(WheelSpin, WheelSpin.telegram_id == User.telegram_id)
        .filter(WheelSpin.status == "COMPLETED").distinct().all()
    }


def select_inactive_users(db: Session, options: CampaignExecutionRequest) -> set[int]:
    if options.inactive_days is None:
        raise HTTPException(422, "inactive_days is required for INACTIVE_USERS")
    cutoff = datetime.now(timezone.utc) - timedelta(days=options.inactive_days)
    return {row[0] for row in _active_users(db).filter(or_(User.last_seen_at.is_(None), User.last_seen_at < cutoff)).all()}


def select_vip_users(db: Session, options: CampaignExecutionRequest) -> set[int]:
    conditions = []
    if options.vip_min_uzs is not None:
        conditions.append(Wallet.uzs_balance >= options.vip_min_uzs)
    if options.vip_min_efc is not None:
        conditions.append(Wallet.efc_balance >= options.vip_min_efc)
    if not conditions:
        raise HTTPException(422, "vip_min_uzs or vip_min_efc is required for VIP_USERS")
    return {row[0] for row in _active_users(db).join(Wallet, Wallet.telegram_id == User.telegram_id).filter(or_(*conditions)).all()}


def select_custom_users(db: Session, options: CampaignExecutionRequest) -> set[int]:
    ids = {int(user_id) for user_id in options.custom_user_ids if int(user_id) > 0}
    if not ids:
        raise HTTPException(422, "custom_user_ids is required for CUSTOM")
    return {row[0] for row in _active_users(db).filter(User.telegram_id.in_(ids)).all()}


SELECTORS = {
    "ALL_USERS": select_all_users,
    "REFERRAL_USERS": select_referral_users,
    "COIN_SHOP_USERS": select_coin_shop_users,
    "ARENA_USERS": select_arena_users,
    "WHEEL_USERS": select_wheel_users,
    "INACTIVE_USERS": select_inactive_users,
    "VIP_USERS": select_vip_users,
    "CUSTOM": select_custom_users,
}


def select_audience(db: Session, audience_type: str, options: CampaignExecutionRequest) -> set[int]:
    selector = SELECTORS.get(audience_type)
    if selector is None:
        raise HTTPException(422, "Unsupported campaign audience")
    return selector(db, options)
