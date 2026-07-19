from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.campaign import Campaign, CampaignRecipient


def claimable(db: Session, now: datetime, stale_before: datetime, batch_size: int, retry_limit: int) -> list[CampaignRecipient]:
    query = (
        db.query(CampaignRecipient)
        .join(Campaign, Campaign.id == CampaignRecipient.campaign_id)
        .filter(
            CampaignRecipient.status == "PENDING",
            CampaignRecipient.retry_count < retry_limit,
            Campaign.deleted_at.is_(None),
            Campaign.status.in_(("RUNNING", "COMPLETED")),
            or_(CampaignRecipient.claimed_at.is_(None), CampaignRecipient.claimed_at <= stale_before),
        )
        .order_by(CampaignRecipient.id.asc())
        .limit(batch_size)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True, of=CampaignRecipient)
    else:
        query = query.with_for_update()
    recipients = query.all()
    for recipient in recipients:
        recipient.claimed_at = now
    db.flush()
    return recipients


def get_locked(db: Session, recipient_id: int) -> CampaignRecipient | None:
    query = db.query(CampaignRecipient).filter(CampaignRecipient.id == recipient_id)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(of=CampaignRecipient)
    else:
        query = query.with_for_update()
    return query.first()
