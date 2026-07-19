from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.coin_promotion import CoinPromotion
from app.models.product import Product
from app.schemas.coin_promotion import CoinPromotionCreate, CoinPromotionUpdate


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _not_found() -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coin promotion not found")


def _product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=422, detail="Coin package not found")
    return product


def _promotion(db: Session, promotion_id: int, include_deleted: bool = False) -> CoinPromotion:
    promotion = db.get(CoinPromotion, promotion_id)
    if promotion is None or (promotion.status == "DELETED" and not include_deleted):
        _not_found()
    return promotion


def _expire_due(items: list[CoinPromotion], now: datetime | None = None) -> bool:
    now = now or utc_now()
    changed = False
    for promotion in items:
        if promotion.status == "ACTIVE" and _utc(promotion.end_at) <= now:
            promotion.status = "EXPIRED"
            changed = True
    return changed


def create(db: Session, data: CoinPromotionCreate) -> CoinPromotion:
    _product(db, data.coin_package_id)
    values = data.model_dump()
    promotion = CoinPromotion(**values, status="DRAFT", reserved_quantity=0, sold_quantity=0)
    db.add(promotion)
    db.commit()
    db.refresh(promotion)
    return promotion


def update(db: Session, promotion_id: int, data: CoinPromotionUpdate) -> CoinPromotion:
    promotion = _promotion(db, promotion_id)
    _product(db, data.coin_package_id)
    if data.total_quantity < promotion.reserved_quantity + promotion.sold_quantity:
        raise HTTPException(status_code=422, detail="total_quantity cannot be less than reserved and sold quantity")
    for key, value in data.model_dump().items():
        setattr(promotion, key, value)
    db.commit()
    db.refresh(promotion)
    return promotion


def detail(db: Session, promotion_id: int, include_deleted: bool = False) -> CoinPromotion:
    promotion = _promotion(db, promotion_id, include_deleted)
    if _expire_due([promotion]):
        db.commit()
        db.refresh(promotion)
    return promotion


def list_all(db: Session, include_deleted: bool = True) -> list[CoinPromotion]:
    query = db.query(CoinPromotion)
    if not include_deleted:
        query = query.filter(CoinPromotion.status != "DELETED")
    items = query.order_by(CoinPromotion.created_at.desc(), CoinPromotion.id.desc()).all()
    if _expire_due(items):
        db.commit()
    return items


def change_status(db: Session, promotion_id: int, target: str) -> CoinPromotion:
    promotion = _promotion(db, promotion_id)
    if target == "ACTIVE" and _utc(promotion.end_at) <= utc_now():
        raise HTTPException(status_code=422, detail="Expired coin promotion cannot be activated")
    promotion.status = target
    db.commit()
    db.refresh(promotion)
    return promotion


def soft_delete(db: Session, promotion_id: int) -> CoinPromotion:
    promotion = _promotion(db, promotion_id)
    promotion.status = "DELETED"
    db.commit()
    db.refresh(promotion)
    return promotion


def restore(db: Session, promotion_id: int) -> CoinPromotion:
    promotion = _promotion(db, promotion_id, include_deleted=True)
    if promotion.status != "DELETED":
        _not_found()
    promotion.status = "EXPIRED" if _utc(promotion.end_at) <= utc_now() else "DRAFT"
    db.commit()
    db.refresh(promotion)
    return promotion
