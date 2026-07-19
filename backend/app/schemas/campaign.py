from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class AudienceType(str, Enum):
    ALL_USERS = "ALL_USERS"
    REFERRAL_USERS = "REFERRAL_USERS"
    COIN_SHOP_USERS = "COIN_SHOP_USERS"
    ARENA_USERS = "ARENA_USERS"
    WHEEL_USERS = "WHEEL_USERS"
    INACTIVE_USERS = "INACTIVE_USERS"
    VIP_USERS = "VIP_USERS"
    CUSTOM = "CUSTOM"


class ScheduleType(str, Enum):
    NOW = "NOW"
    SCHEDULED = "SCHEDULED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    DELETED = "DELETED"


class CampaignAction(str, Enum):
    NONE = "NONE"
    COIN_SHOP = "COIN_SHOP"
    REFERRAL = "REFERRAL"
    ARENA = "ARENA"
    WHEEL = "WHEEL"
    PROFILE = "PROFILE"
    URL = "URL"
    CUSTOM = "CUSTOM"


class CampaignFields(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1)
    image_url: str | None = Field(default=None, max_length=1000)
    badge: str | None = Field(default=None, max_length=80)
    button_text: str | None = Field(default=None, max_length=100)
    button_action: CampaignAction = CampaignAction.NONE
    button_target: str | None = Field(default=None, max_length=1000)
    promotion_id: int | None = Field(default=None, gt=0)
    audience_type: AudienceType = AudienceType.ALL_USERS
    schedule_type: ScheduleType = ScheduleType.NOW
    scheduled_at: datetime | None = None

    @model_validator(mode="after")
    def validate_contract(self):
        if self.schedule_type == ScheduleType.SCHEDULED and self.scheduled_at is None:
            raise ValueError("scheduled_at is required for SCHEDULED campaigns")
        if self.button_action in {CampaignAction.URL, CampaignAction.CUSTOM} and not self.button_target:
            raise ValueError("button_target is required for URL and CUSTOM actions")
        return self


class CampaignCreate(CampaignFields):
    status: CampaignStatus = CampaignStatus.DRAFT


class CampaignUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    message: str | None = Field(default=None, min_length=1)
    image_url: str | None = Field(default=None, max_length=1000)
    badge: str | None = Field(default=None, max_length=80)
    button_text: str | None = Field(default=None, max_length=100)
    button_action: CampaignAction | None = None
    button_target: str | None = Field(default=None, max_length=1000)
    promotion_id: int | None = Field(default=None, gt=0)
    audience_type: AudienceType | None = None
    schedule_type: ScheduleType | None = None
    scheduled_at: datetime | None = None


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    message: str
    image_url: str | None
    badge: str | None
    button_text: str | None
    button_action: CampaignAction
    button_target: str | None
    promotion_id: int | None
    audience_type: AudienceType
    schedule_type: ScheduleType
    scheduled_at: datetime | None
    status: CampaignStatus
    sent_count: int
    opened_count: int
    clicked_count: int
    failed_count: int
    created_by: int
    updated_by: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    @computed_field
    @property
    def ctr(self) -> float:
        return round(self.clicked_count / self.sent_count * 100, 2) if self.sent_count else 0.0

    @computed_field
    @property
    def failure_rate(self) -> float:
        return round(self.failed_count / self.sent_count * 100, 2) if self.sent_count else 0.0


class CampaignExecutionRequest(BaseModel):
    custom_user_ids: list[int] = Field(default_factory=list, max_length=100000)
    inactive_days: int | None = Field(default=None, ge=1, le=3650)
    vip_min_uzs: float | None = Field(default=None, ge=0)
    vip_min_efc: float | None = Field(default=None, ge=0)


class CampaignRecipientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    user_id: int
    status: str
    opened_at: datetime | None
    read_at: datetime | None
    clicked_at: datetime | None
    dismissed_at: datetime | None
    created_at: datetime


class CampaignExecutionResponse(BaseModel):
    campaign: CampaignResponse
    recipient_count: int
