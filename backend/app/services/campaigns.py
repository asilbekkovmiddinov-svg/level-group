from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.crud.campaign import create_campaign, update_campaign
from app.models.campaign import Campaign
from app.models.promotion import Promotion
from app.repositories import campaigns as repository
from app.schemas.campaign import CampaignCreate, CampaignUpdate


TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _not_found() -> None:
    raise HTTPException(404, "Campaign not found")


def _enum_values(values: dict) -> dict:
    return {key: getattr(value, "value", value) for key, value in values.items()}


def _validate_promotion(db: Session, promotion_id: int | None) -> None:
    if promotion_id is not None and db.query(Promotion.id).filter(Promotion.id == promotion_id, Promotion.deleted_at.is_(None)).first() is None:
        raise HTTPException(422, "promotion_id must reference an existing promotion")


def _validate_combined(campaign: Campaign | None, values: dict) -> None:
    schedule_type = values.get("schedule_type", getattr(campaign, "schedule_type", "NOW"))
    scheduled_at = values.get("scheduled_at", getattr(campaign, "scheduled_at", None))
    action = values.get("button_action", getattr(campaign, "button_action", "NONE"))
    target = values.get("button_target", getattr(campaign, "button_target", None))
    if schedule_type == "SCHEDULED" and scheduled_at is None:
        raise HTTPException(422, "scheduled_at is required for SCHEDULED campaigns")
    if action in {"URL", "CUSTOM"} and not target:
        raise HTTPException(422, "button_target is required for URL and CUSTOM actions")


def create(db: Session, data: CampaignCreate, actor_id: int) -> Campaign:
    values = _enum_values(data.model_dump())
    _validate_combined(None, values)
    _validate_promotion(db, values.get("promotion_id"))
    if values["status"] not in {"DRAFT", "SCHEDULED"}:
        raise HTTPException(409, "Campaign can only be created as DRAFT or SCHEDULED")
    if values["status"] == "SCHEDULED" and values["schedule_type"] != "SCHEDULED":
        raise HTTPException(409, "SCHEDULED status requires SCHEDULED schedule_type")
    campaign = create_campaign(values, actor_id)
    repository.add(db, campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def update(db: Session, campaign_id: int, data: CampaignUpdate, actor_id: int) -> Campaign:
    campaign = repository.get(db, campaign_id, lock=True)
    if campaign is None:
        _not_found()
    if campaign.status in TERMINAL_STATUSES | {"RUNNING"}:
        raise HTTPException(409, f"{campaign.status} campaign cannot be edited")
    values = _enum_values(data.model_dump(exclude_unset=True))
    _validate_combined(campaign, values)
    _validate_promotion(db, values.get("promotion_id", campaign.promotion_id))
    update_campaign(campaign, values, actor_id)
    db.commit()
    db.refresh(campaign)
    return campaign


def detail(db: Session, campaign_id: int, include_deleted: bool = False) -> Campaign:
    campaign = repository.get(db, campaign_id, include_deleted=include_deleted)
    if campaign is None:
        _not_found()
    return campaign


def list_campaigns(db: Session, include_deleted: bool = False) -> list[Campaign]:
    return repository.list_all(db, include_deleted=include_deleted)


def soft_delete(db: Session, campaign_id: int, actor_id: int) -> Campaign:
    campaign = repository.get(db, campaign_id, lock=True)
    if campaign is None:
        _not_found()
    if campaign.status == "RUNNING":
        raise HTTPException(409, "RUNNING campaign must be paused or cancelled before deletion")
    campaign.status = "DELETED"
    campaign.deleted_at = utc_now()
    campaign.updated_by = actor_id
    db.commit()
    db.refresh(campaign)
    return campaign


def restore(db: Session, campaign_id: int, actor_id: int) -> Campaign:
    campaign = repository.get(db, campaign_id, include_deleted=True, lock=True)
    if campaign is None or campaign.deleted_at is None:
        _not_found()
    campaign.deleted_at = None
    campaign.status = "SCHEDULED" if campaign.schedule_type == "SCHEDULED" and campaign.scheduled_at and _utc(campaign.scheduled_at) > utc_now() else "DRAFT"
    campaign.updated_by = actor_id
    db.commit()
    db.refresh(campaign)
    return campaign


def transition(db: Session, campaign_id: int, action: str, actor_id: int) -> Campaign:
    campaign = repository.get(db, campaign_id, lock=True)
    if campaign is None:
        _not_found()
    allowed = {
        "pause": ({"SCHEDULED", "RUNNING"}, "PAUSED"),
        "cancel": ({"DRAFT", "SCHEDULED", "RUNNING", "PAUSED"}, "CANCELLED"),
    }
    if action == "resume":
        if campaign.status != "PAUSED":
            raise HTTPException(409, "Only PAUSED campaigns can be resumed")
        target = "SCHEDULED" if campaign.schedule_type == "SCHEDULED" and campaign.scheduled_at and _utc(campaign.scheduled_at) > utc_now() else "DRAFT"
    else:
        sources, target = allowed[action]
        if campaign.status not in sources:
            raise HTTPException(409, f"Campaign cannot {action} from {campaign.status}")
    campaign.status = target
    campaign.updated_by = actor_id
    db.commit()
    db.refresh(campaign)
    return campaign
