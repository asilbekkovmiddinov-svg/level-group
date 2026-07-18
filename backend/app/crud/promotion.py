from sqlalchemy.orm import Session

from app.models.promotion import Promotion
from app.repositories import promotions as repository


def create_promotion(db: Session, values: dict, actor_id: int | None) -> Promotion:
    promotion = Promotion(**values, created_by=actor_id, updated_by=actor_id)
    return repository.add(db, promotion)


def update_promotion(promotion: Promotion, values: dict, actor_id: int | None) -> Promotion:
    for field, value in values.items():
        setattr(promotion, field, value)
    promotion.updated_by = actor_id
    return promotion


def set_status(promotion: Promotion, status: str, actor_id: int | None) -> Promotion:
    promotion.status = status
    promotion.updated_by = actor_id
    return promotion
