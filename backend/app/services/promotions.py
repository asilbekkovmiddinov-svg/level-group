from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.crud.promotion import create_promotion, set_status, update_promotion
from app.models.promotion import Promotion
from app.repositories import promotions as repository
from app.schemas.promotion import PromotionCreate, PromotionUpdate


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def synchronize_schedule(db: Session, now: datetime | None = None) -> None:
    now = now or utc_now()
    changed = False
    for promotion in repository.lock_all_live(db):
        if promotion.end_at is not None and _utc(promotion.end_at) <= now:
            promotion.status = "EXPIRED"
            changed = True
        elif promotion.status == "SCHEDULED" and (
            promotion.start_at is None or _utc(promotion.start_at) <= now
        ):
            promotion.status = "ACTIVE"
            changed = True
    if changed:
        db.flush()


def _not_found() -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion not found")


def _validate_combined(promotion: Promotion, values: dict) -> None:
    start_at = values.get("start_at", promotion.start_at)
    end_at = values.get("end_at", promotion.end_at)
    action = values.get("button_action", promotion.button_action)
    target = values.get("button_target", promotion.button_target)
    if start_at and end_at and _utc(end_at) <= _utc(start_at):
        raise HTTPException(status_code=422, detail="end_at must be later than start_at")
    if str(action) in {"ButtonAction.URL", "ButtonAction.CUSTOM", "URL", "CUSTOM"} and not target:
        raise HTTPException(status_code=422, detail="button_target is required for URL and CUSTOM actions")


def create(db: Session, data: PromotionCreate, actor_id: int | None) -> Promotion:
    values = data.model_dump()
    values["status"] = data.status.value
    values["button_action"] = data.button_action.value
    now = utc_now()
    if values["end_at"] and _utc(values["end_at"]) <= now:
        values["status"] = "EXPIRED"
    elif values["status"] == "SCHEDULED" and (
        values["start_at"] is None or _utc(values["start_at"]) <= now
    ):
        values["status"] = "ACTIVE"
    promotion = create_promotion(db, values, actor_id)
    db.commit()
    db.refresh(promotion)
    return promotion


def update(db: Session, promotion_id: int, data: PromotionUpdate, actor_id: int | None) -> Promotion:
    synchronize_schedule(db)
    promotion = repository.get(db, promotion_id)
    if promotion is None:
        _not_found()
    values = data.model_dump(exclude_unset=True)
    if "button_action" in values and values["button_action"] is not None:
        values["button_action"] = values["button_action"].value
    _validate_combined(promotion, values)
    update_promotion(promotion, values, actor_id)
    db.commit()
    db.refresh(promotion)
    return promotion


def detail(db: Session, promotion_id: int, include_deleted: bool = False) -> Promotion:
    synchronize_schedule(db)
    promotion = repository.get(db, promotion_id, include_deleted=include_deleted)
    if promotion is None:
        _not_found()
    db.commit()
    db.refresh(promotion)
    return promotion


def list_promotions(db: Session, include_deleted: bool = False) -> list[Promotion]:
    synchronize_schedule(db)
    db.commit()
    return repository.list_all(db, include_deleted=include_deleted)


def change_status(db: Session, promotion_id: int, target: str, actor_id: int | None) -> Promotion:
    promotion = repository.get(db, promotion_id)
    if promotion is None:
        _not_found()
    now = utc_now()
    if target == "ACTIVE":
        if promotion.end_at and _utc(promotion.end_at) <= now:
            target = "EXPIRED"
        elif promotion.start_at and _utc(promotion.start_at) > now:
            target = "SCHEDULED"
    set_status(promotion, target, actor_id)
    db.commit()
    db.refresh(promotion)
    return promotion


def soft_delete(db: Session, promotion_id: int, actor_id: int | None) -> Promotion:
    promotion = repository.get(db, promotion_id)
    if promotion is None:
        _not_found()
    promotion.status = "DELETED"
    promotion.deleted_at = utc_now()
    promotion.updated_by = actor_id
    db.commit()
    db.refresh(promotion)
    return promotion


def restore(db: Session, promotion_id: int, actor_id: int | None) -> Promotion:
    promotion = repository.get(db, promotion_id, include_deleted=True)
    if promotion is None or promotion.deleted_at is None:
        _not_found()
    now = utc_now()
    promotion.deleted_at = None
    promotion.updated_by = actor_id
    if promotion.end_at and _utc(promotion.end_at) <= now:
        promotion.status = "EXPIRED"
    elif promotion.start_at and _utc(promotion.start_at) > now:
        promotion.status = "SCHEDULED"
    else:
        promotion.status = "DRAFT"
    db.commit()
    db.refresh(promotion)
    return promotion


def public_active(db: Session) -> list[Promotion]:
    synchronize_schedule(db)
    db.commit()
    return repository.list_public_active(db)
