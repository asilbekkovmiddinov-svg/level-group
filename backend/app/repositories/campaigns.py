from sqlalchemy.orm import Session

from app.models.campaign import Campaign


def add(db: Session, campaign: Campaign) -> Campaign:
    db.add(campaign)
    db.flush()
    return campaign


def get(db: Session, campaign_id: int, include_deleted: bool = False, lock: bool = False) -> Campaign | None:
    query = db.query(Campaign).filter(Campaign.id == campaign_id)
    if not include_deleted:
        query = query.filter(Campaign.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    return query.first()


def list_all(db: Session, include_deleted: bool = False) -> list[Campaign]:
    query = db.query(Campaign)
    if not include_deleted:
        query = query.filter(Campaign.deleted_at.is_(None))
    return query.order_by(Campaign.created_at.desc(), Campaign.id.desc()).all()
