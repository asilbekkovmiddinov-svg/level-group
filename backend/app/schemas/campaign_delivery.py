from datetime import datetime

from pydantic import BaseModel, Field


class DeliveryClaimResponse(BaseModel):
    recipient_id: int
    campaign_id: int
    telegram_id: int
    title: str
    message: str
    image_url: str | None
    button_text: str | None
    button_action: str
    button_target: str | None
    promotion_id: int | None
    claimed_at: datetime


class DeliverySentRequest(BaseModel):
    claimed_at: datetime
    delivery_time: float = Field(ge=0)


class DeliveryFailedRequest(BaseModel):
    claimed_at: datetime
    failure_reason: str = Field(min_length=1, max_length=500)
    temporary: bool = False
    delivery_time: float = Field(ge=0)


class DeliveryResultResponse(BaseModel):
    recipient_id: int
    campaign_id: int
    status: str
    sent_at: datetime | None
    failed_at: datetime | None
    retry_count: int
    final: bool


class CampaignStatisticsResponse(BaseModel):
    campaign_id: int
    sent_count: int
    opened_count: int
    clicked_count: int
    failed_count: int
    ctr: float
    failure_rate: float
