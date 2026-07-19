from sqlalchemy.orm import Session

from app.models.promotion import Promotion


def add(db: Session, promotion: Promotion) -> Promotion:
    db.add(promotion)
    db.flush()
    return promotion


def get(db: Session, promotion_id: int, include_deleted: bool = False) -> Promotion | None:
    query = db.query(Promotion).filter(Promotion.id == promotion_id)
    if not include_deleted:
        query = query.filter(Promotion.deleted_at.is_(None))
    return query.first()


def list_all(db: Session, include_deleted: bool = False) -> list[Promotion]:
    query = db.query(Promotion)
    if not include_deleted:
        query = query.filter(Promotion.deleted_at.is_(None))
    return query.order_by(Promotion.priority.desc(), Promotion.id.desc()).all()


def list_public_active(db: Session) -> list[Promotion]:
    return (
        db.query(Promotion)
        .filter(
            Promotion.status == "ACTIVE",
            Promotion.deleted_at.is_(None),
            (Promotion.max_views.is_(None)) | (Promotion.view_count < Promotion.max_views),
            (Promotion.max_clicks.is_(None)) | (Promotion.click_count < Promotion.max_clicks),
        )
        .order_by(Promotion.priority.desc(), Promotion.id.desc())
        .all()
    )


def lock_all_live(db: Session) -> list[Promotion]:
    return (
        db.query(Promotion)
        .filter(
            Promotion.deleted_at.is_(None),
            Promotion.status.in_(("SCHEDULED", "ACTIVE")),
        )
        .with_for_update()
        .all()
    )
