import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import (
    CAMPAIGN_DELIVERY_BATCH_SIZE, CAMPAIGN_DELIVERY_CLAIM_TTL_SECONDS,
    CAMPAIGN_DELIVERY_RETRY_LIMIT,
)
from app.models.campaign import Campaign
from app.repositories import campaign_delivery as repository
from app.schemas.campaign_delivery import DeliveryFailedRequest, DeliverySentRequest
from app.services.campaign_execution import synchronize_statistics


logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _same_timestamp(left: datetime | None, right: datetime) -> bool:
    if left is None:
        return False
    left_utc = left.replace(tzinfo=timezone.utc) if left.tzinfo is None else left.astimezone(timezone.utc)
    right_utc = right.replace(tzinfo=timezone.utc) if right.tzinfo is None else right.astimezone(timezone.utc)
    return left_utc == right_utc


def claim(db: Session) -> list[dict]:
    started = time.monotonic()
    now = utc_now()
    rows = repository.claimable(
        db, now, now - timedelta(seconds=CAMPAIGN_DELIVERY_CLAIM_TTL_SECONDS),
        CAMPAIGN_DELIVERY_BATCH_SIZE, CAMPAIGN_DELIVERY_RETRY_LIMIT,
    )
    campaigns = {
        item.id: item for item in db.query(Campaign).filter(
            Campaign.id.in_({recipient.campaign_id for recipient in rows})
        ).all()
    } if rows else {}
    result = []
    for recipient in rows:
        campaign = campaigns[recipient.campaign_id]
        result.append({
            "recipient_id": recipient.id, "campaign_id": campaign.id,
            "telegram_id": recipient.user_id, "title": campaign.title,
            "message": campaign.message, "image_url": campaign.image_url,
            "button_text": campaign.button_text, "button_action": campaign.button_action,
            "button_target": campaign.button_target, "promotion_id": campaign.promotion_id,
            "claimed_at": now,
        })
    db.commit()
    logger.info("campaign_delivery_claim count=%s execution_seconds=%.6f", len(result), time.monotonic() - started)
    return result


def sent(db: Session, recipient_id: int, data: DeliverySentRequest):
    started = time.monotonic()
    recipient = repository.get_locked(db, recipient_id)
    if recipient is None:
        raise HTTPException(404, "Campaign recipient not found")
    if recipient.status == "SENT":
        return recipient, True
    if recipient.status != "PENDING" or not _same_timestamp(recipient.claimed_at, data.claimed_at):
        raise HTTPException(409, "Delivery claim is no longer active")
    recipient.status = "SENT"
    recipient.sent_at = utc_now()
    recipient.delivery_time = data.delivery_time
    recipient.failure_reason = None
    db.commit()
    logger.info("campaign_delivery_sent recipient_id=%s execution_seconds=%.6f", recipient.id, time.monotonic() - started)
    return recipient, True


def failed(db: Session, recipient_id: int, data: DeliveryFailedRequest):
    started = time.monotonic()
    recipient = repository.get_locked(db, recipient_id)
    if recipient is None:
        raise HTTPException(404, "Campaign recipient not found")
    if recipient.status == "FAILED":
        return recipient, True
    if _same_timestamp(recipient.last_failed_claimed_at, data.claimed_at):
        return recipient, recipient.status == "FAILED"
    if recipient.status != "PENDING" or not _same_timestamp(recipient.claimed_at, data.claimed_at):
        raise HTTPException(409, "Delivery claim is no longer active")
    recipient.retry_count += 1
    recipient.failed_at = utc_now()
    recipient.failure_reason = data.failure_reason
    recipient.delivery_time = data.delivery_time
    recipient.last_failed_claimed_at = recipient.claimed_at
    final = not data.temporary or recipient.retry_count >= CAMPAIGN_DELIVERY_RETRY_LIMIT
    if final:
        recipient.status = "FAILED"
    else:
        recipient.claimed_at = None
    db.commit()
    logger.info(
        "campaign_delivery_%s recipient_id=%s retry_count=%s execution_seconds=%.6f",
        "failed" if final else "retry", recipient.id, recipient.retry_count, time.monotonic() - started,
    )
    return recipient, final


def recalculate(db: Session, campaign_id: int) -> Campaign:
    started = time.monotonic()
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.deleted_at.is_(None)).with_for_update().first()
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    synchronize_statistics(db, campaign)
    db.commit()
    logger.info("campaign_delivery_statistics campaign_id=%s execution_seconds=%.6f", campaign.id, time.monotonic() - started)
    return campaign
