from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schemas.campaign import CampaignAction


class NotificationStatus(str, Enum):
    UNREAD = "UNREAD"
    READ = "READ"
    CLICKED = "CLICKED"
    DISMISSED = "DISMISSED"


class NotificationResponse(BaseModel):
    id: int
    title: str
    message: str
    image_url: str | None
    badge: str | None
    button_action: CampaignAction
    button_target: str | None
    promotion_id: int | None
    status: NotificationStatus
    created_at: datetime
    read_at: datetime | None
    clicked_at: datetime | None
    dismissed_at: datetime | None


class UnreadCountResponse(BaseModel):
    unread_count: int


class ReadAllResponse(BaseModel):
    updated_count: int
    unread_count: int
