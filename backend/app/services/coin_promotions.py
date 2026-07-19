from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.coin_promotion import CoinPromotion
from app.models.order import Order


COUNTED_ORDER_STATUSES = ("WAITING_OPERATOR", "CLAIMED", "COMPLETED")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def active_for_product(db: Session, product_id: int, *, lock: bool = False, now: datetime | None = None):
    now = now or utc_now()
    query = db.query(CoinPromotion).filter(
        CoinPromotion.coin_package_id == product_id,
        CoinPromotion.status == "ACTIVE",
        CoinPromotion.start_at <= now,
        CoinPromotion.end_at > now,
        CoinPromotion.reserved_quantity + CoinPromotion.sold_quantity < CoinPromotion.total_quantity,
    ).order_by(CoinPromotion.start_at.desc(), CoinPromotion.id.desc())
    if lock:
        query = query.with_for_update()
    return query.first()


def reserve(db: Session, product_id: int, telegram_id: int):
    promotion = active_for_product(db, product_id, lock=True)
    if promotion is None:
        return None, None
    user_count = db.query(Order.id).filter(
        Order.telegram_id == telegram_id,
        Order.promotion_id == promotion.id,
        Order.status.in_(COUNTED_ORDER_STATUSES),
    ).count()
    if user_count >= promotion.per_user_limit:
        return promotion, "user_limit"
    promotion.reserved_quantity += 1
    db.flush()
    return promotion, None


def confirm_locked(db: Session, promotion_id: int | None):
    if promotion_id is None:
        return None
    promotion = db.query(CoinPromotion).filter(CoinPromotion.id == promotion_id).with_for_update().first()
    if promotion is None:
        return None
    if promotion.reserved_quantity <= 0:
        raise RuntimeError("Promotion reservation is missing")
    promotion.reserved_quantity -= 1
    promotion.sold_quantity += 1
    db.flush()
    return promotion


def release_locked(db: Session, promotion_id: int | None):
    if promotion_id is None:
        return None
    promotion = db.query(CoinPromotion).filter(CoinPromotion.id == promotion_id).with_for_update().first()
    if promotion is None:
        return None
    if promotion.reserved_quantity > 0:
        promotion.reserved_quantity -= 1
        db.flush()
    return promotion


def product_promotion(db: Session, product_id: int):
    promotion = active_for_product(db, product_id)
    if promotion is None:
        return None
    return {
        "original_price": float(promotion.original_price),
        "promotion_price": float(promotion.promotion_price),
        "remaining_quantity": promotion.remaining_quantity,
        "promotion_id": promotion.id,
    }
