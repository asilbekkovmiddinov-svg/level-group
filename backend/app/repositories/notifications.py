from sqlalchemy.orm import Session

from app.models.campaign import Campaign, CampaignRecipient


VISIBLE_CAMPAIGN_STATUSES = ("RUNNING", "COMPLETED")
VISIBLE_RECIPIENT_STATUSES = ("PENDING", "SENT", "OPENED", "CLICKED")
UNREAD_RECIPIENT_STATUSES = ("PENDING", "SENT")


def list_for_user(db: Session, telegram_id: int) -> list[tuple[CampaignRecipient, Campaign]]:
    return (
        db.query(CampaignRecipient, Campaign)
        .join(Campaign, Campaign.id == CampaignRecipient.campaign_id)
        .filter(
            CampaignRecipient.user_id == telegram_id,
            CampaignRecipient.dismissed_at.is_(None),
            CampaignRecipient.status.in_(VISIBLE_RECIPIENT_STATUSES),
            Campaign.status.in_(VISIBLE_CAMPAIGN_STATUSES),
            Campaign.deleted_at.is_(None),
        )
        .order_by(CampaignRecipient.created_at.desc(), CampaignRecipient.id.desc())
        .all()
    )


def unread_count(db: Session, telegram_id: int) -> int:
    return (
        db.query(CampaignRecipient)
        .join(Campaign, Campaign.id == CampaignRecipient.campaign_id)
        .filter(
            CampaignRecipient.user_id == telegram_id,
            CampaignRecipient.dismissed_at.is_(None),
            CampaignRecipient.status.in_(UNREAD_RECIPIENT_STATUSES),
            Campaign.status.in_(VISIBLE_CAMPAIGN_STATUSES),
            Campaign.deleted_at.is_(None),
        ).count()
    )


def get_with_campaign(db: Session, notification_id: int, lock: bool = False) -> tuple[CampaignRecipient, Campaign] | None:
    query = db.query(CampaignRecipient, Campaign).join(Campaign, Campaign.id == CampaignRecipient.campaign_id).filter(CampaignRecipient.id == notification_id)
    if lock:
        query = query.with_for_update()
    return query.first()


def unread_for_user(db: Session, telegram_id: int) -> list[CampaignRecipient]:
    return (
        db.query(CampaignRecipient)
        .join(Campaign, Campaign.id == CampaignRecipient.campaign_id)
        .filter(
            CampaignRecipient.user_id == telegram_id,
            CampaignRecipient.dismissed_at.is_(None),
            CampaignRecipient.status.in_(UNREAD_RECIPIENT_STATUSES),
            Campaign.status.in_(VISIBLE_CAMPAIGN_STATUSES),
            Campaign.deleted_at.is_(None),
        ).with_for_update().all()
    )
