from fastapi import HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.campaign import Campaign, CampaignRecipient
from app.repositories import campaigns as repository
from app.schemas.campaign import CampaignExecutionRequest
from app.services.campaign_audience import select_audience
from app.services.campaigns import utc_now, _utc


def _campaign(db: Session, campaign_id: int) -> Campaign:
    campaign = repository.get(db, campaign_id, lock=True)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    return campaign


def schedule(db: Session, campaign_id: int, actor_id: int) -> Campaign:
    campaign = _campaign(db, campaign_id)
    if campaign.status != "DRAFT":
        raise HTTPException(409, "Only DRAFT campaigns can be scheduled")
    campaign.status = "SCHEDULED"
    campaign.updated_by = actor_id
    db.commit()
    db.refresh(campaign)
    return campaign


def prepare(db: Session, campaign_id: int, options: CampaignExecutionRequest, actor_id: int) -> tuple[Campaign, int]:
    campaign = _campaign(db, campaign_id)
    if campaign.status != "SCHEDULED":
        raise HTTPException(409, "Only SCHEDULED campaigns can be prepared")
    if campaign.schedule_type == "SCHEDULED" and campaign.scheduled_at and _utc(campaign.scheduled_at) > utc_now():
        raise HTTPException(409, "Campaign scheduled time has not arrived")
    if repository.recipient_count(db, campaign.id):
        raise HTTPException(409, "Campaign recipient snapshot already exists")
    try:
        user_ids = select_audience(db, campaign.audience_type, options)
        db.add_all(CampaignRecipient(campaign_id=campaign.id, user_id=user_id) for user_id in sorted(user_ids))
        campaign.status = "READY"
        campaign.updated_by = actor_id
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        failed = repository.get(db, campaign_id, lock=True)
        if failed is not None:
            failed.status = "FAILED"
            failed.updated_by = actor_id
            db.commit()
        raise HTTPException(500, "Campaign audience preparation failed") from error
    db.refresh(campaign)
    return campaign, len(user_ids)


def start(db: Session, campaign_id: int, actor_id: int) -> Campaign:
    campaign = _campaign(db, campaign_id)
    if campaign.status != "READY":
        raise HTTPException(409, "Only READY campaigns can start")
    campaign.status = "RUNNING"
    campaign.updated_by = actor_id
    db.commit()
    db.refresh(campaign)
    return campaign


def complete(db: Session, campaign_id: int, actor_id: int) -> Campaign:
    campaign = _campaign(db, campaign_id)
    if campaign.status != "RUNNING":
        raise HTTPException(409, "Only RUNNING campaigns can complete")
    synchronize_statistics(db, campaign)
    campaign.status = "COMPLETED"
    campaign.updated_by = actor_id
    db.commit()
    db.refresh(campaign)
    return campaign


def synchronize_statistics(db: Session, campaign: Campaign) -> Campaign:
    sent_statuses = ("SENT", "OPENED", "CLICKED")
    values = db.query(
        func.sum(case((CampaignRecipient.status.in_(sent_statuses), 1), else_=0)),
        func.sum(case((CampaignRecipient.status.in_(("OPENED", "CLICKED")), 1), else_=0)),
        func.sum(case((CampaignRecipient.status == "CLICKED", 1), else_=0)),
        func.sum(case((CampaignRecipient.status == "FAILED", 1), else_=0)),
    ).filter(CampaignRecipient.campaign_id == campaign.id).one()
    campaign.sent_count = int(values[0] or 0)
    campaign.opened_count = int(values[1] or 0)
    campaign.clicked_count = int(values[2] or 0)
    campaign.failed_count = int(values[3] or 0)
    return campaign


def recipient_list(db: Session, campaign_id: int) -> list[CampaignRecipient]:
    campaign = repository.get(db, campaign_id, include_deleted=True)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    return repository.recipients(db, campaign_id)
