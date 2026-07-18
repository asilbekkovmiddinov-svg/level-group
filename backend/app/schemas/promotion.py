from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PromotionStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class ButtonAction(str, Enum):
    NONE = "NONE"
    COIN_SHOP = "COIN_SHOP"
    REFERRAL = "REFERRAL"
    ARENA = "ARENA"
    WHEEL = "WHEEL"
    PROFILE = "PROFILE"
    URL = "URL"
    CUSTOM = "CUSTOM"


class PromotionFields(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    subtitle: str | None = Field(default=None, max_length=240)
    description: str | None = None
    banner_url: str | None = Field(default=None, max_length=1000)
    badge: str | None = Field(default=None, max_length=80)
    button_text: str | None = Field(default=None, max_length=100)
    button_action: ButtonAction = ButtonAction.NONE
    button_target: str | None = Field(default=None, max_length=1000)
    priority: int = Field(default=0, ge=0)
    start_at: datetime | None = None
    end_at: datetime | None = None
    max_views: int | None = Field(default=None, gt=0)
    max_clicks: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_contract(self):
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        if self.button_action in {ButtonAction.URL, ButtonAction.CUSTOM} and not self.button_target:
            raise ValueError("button_target is required for URL and CUSTOM actions")
        return self


class PromotionCreate(PromotionFields):
    status: PromotionStatus = PromotionStatus.DRAFT


class PromotionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    subtitle: str | None = Field(default=None, max_length=240)
    description: str | None = None
    banner_url: str | None = Field(default=None, max_length=1000)
    badge: str | None = Field(default=None, max_length=80)
    button_text: str | None = Field(default=None, max_length=100)
    button_action: ButtonAction | None = None
    button_target: str | None = Field(default=None, max_length=1000)
    priority: int | None = Field(default=None, ge=0)
    start_at: datetime | None = None
    end_at: datetime | None = None
    max_views: int | None = Field(default=None, gt=0)
    max_clicks: int | None = Field(default=None, gt=0)


class PromotionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    subtitle: str | None
    description: str | None
    banner_url: str | None
    banner_uploaded: bool = False
    banner_content_type: str | None = None
    banner_size: int | None = None
    banner_updated_at: datetime | None = None
    badge: str | None
    button_text: str | None
    button_action: ButtonAction
    button_target: str | None
    priority: int
    status: PromotionStatus
    start_at: datetime | None
    end_at: datetime | None
    max_views: int | None
    max_clicks: int | None
    view_count: int
    click_count: int
    last_viewed_at: datetime | None = None
    last_clicked_at: datetime | None = None
    created_by: int | None
    updated_by: int | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class PublicPromotionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    subtitle: str | None
    description: str | None
    banner_url: str | None
    badge: str | None
    button_text: str | None
    button_action: ButtonAction
    button_target: str | None
    priority: int
    start_at: datetime | None
    end_at: datetime | None
