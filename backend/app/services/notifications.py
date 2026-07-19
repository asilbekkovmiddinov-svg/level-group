from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.campaign import Campaign, CampaignRecipient
from app.repositories import notifications as repository
from app.services.campaign_execution import synchronize_statistics


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def public_status(recipient: CampaignRecipient) -> str:
    if recipient.dismissed_at is not None:
        return "DISMISSED"
    if recipient.status == "CLICKED":
        return "CLICKED"
    if recipient.status == "OPENED":
        return "READ"
    return "UNREAD"


def response(recipient: CampaignRecipient, campaign: Campaign) -> dict:
    return {
        "id": recipient.id,
        "title": campaign.title,
        "message": campaign.message,
        "image_url": campaign.image_url,
        "badge": campaign.badge,
        "button_action": campaign.button_action,
        "button_target": campaign.button_target,
        "promotion_id": campaign.promotion_id,
        "status": public_status(recipient),
        "created_at": recipient.created_at,
        "read_at": recipient.read_at,
        "clicked_at": recipient.clicked_at,
        "dismissed_at": recipient.dismissed_at,
    }


def _owned(db: Session, notification_id: int, telegram_id: int) -> tuple[CampaignRecipient, Campaign]:
    record = repository.get_with_campaign(db, notification_id, lock=True)
    if record is None:
        raise HTTPException(404, "Notification not found")
    recipient, campaign = record
    if recipient.user_id != telegram_id:
        raise HTTPException(403, "Notification belongs to another user")
    if recipient.status not in repository.VISIBLE_RECIPIENT_STATUSES or campaign.status not in repository.VISIBLE_CAMPAIGN_STATUSES:
        raise HTTPException(409, "Notification is not available")
    return recipient, campaign


def list_notifications(db: Session, telegram_id: int) -> list[dict]:
    return [response(recipient, campaign) for recipient, campaign in repository.list_for_user(db, telegram_id)]


def count_unread(db: Session, telegram_id: int) -> int:
    return repository.unread_count(db, telegram_id)


def mark_read(db: Session, notification_id: int, telegram_id: int) -> dict:
    recipient, campaign = _owned(db, notification_id, telegram_id)
    if recipient.dismissed_at is not None:
        raise HTTPException(409, "Dismissed notification cannot be read")
    if recipient.status in repository.UNREAD_RECIPIENT_STATUSES:
        now = utc_now()
        recipient.status = "OPENED"
        recipient.opened_at = recipient.opened_at or now
        recipient.read_at = recipient.read_at or now
        synchronize_statistics(db, campaign)
        db.commit()
        db.refresh(recipient)
        db.refresh(campaign)
    return response(recipient, campaign)


def mark_all_read(db: Session, telegram_id: int) -> dict:
    recipients = repository.unread_for_user(db, telegram_id)
    now = utc_now()
    campaign_ids = set()
    for recipient in recipients:
        recipient.status = "OPENED"
        recipient.opened_at = recipient.opened_at or now
        recipient.read_at = recipient.read_at or now
        campaign_ids.add(recipient.campaign_id)
    db.flush()
    for campaign in db.query(Campaign).filter(Campaign.id.in_(campaign_ids)).with_for_update().all():
        synchronize_statistics(db, campaign)
    db.commit()
    return {"updated_count": len(recipients), "unread_count": repository.unread_count(db, telegram_id)}


def mark_clicked(db: Session, notification_id: int, telegram_id: int) -> dict:
    recipient, campaign = _owned(db, notification_id, telegram_id)
    if recipient.dismissed_at is not None:
        raise HTTPException(409, "Dismissed notification cannot be clicked")
    if recipient.status != "CLICKED":
        now = utc_now()
        recipient.status = "CLICKED"
        recipient.opened_at = recipient.opened_at or now
        recipient.read_at = recipient.read_at or now
        recipient.clicked_at = recipient.clicked_at or now
        synchronize_statistics(db, campaign)
        db.commit()
        db.refresh(recipient)
        db.refresh(campaign)
    return response(recipient, campaign)


def dismiss(db: Session, notification_id: int, telegram_id: int) -> dict:
    recipient, campaign = _owned(db, notification_id, telegram_id)
    if recipient.dismissed_at is None:
        recipient.dismissed_at = utc_now()
        db.commit()
        db.refresh(recipient)
    return response(recipient, campaign)
