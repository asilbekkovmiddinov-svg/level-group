import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


CHAT_ID_PATTERN = re.compile(r"^(?:@[A-Za-z0-9_]{5,32}|-\d{5,20})$")


class SubscriptionChannelPayload(BaseModel):
    chat_id: str = Field(min_length=2, max_length=128)
    title: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=12, max_length=512)
    sort_order: int = Field(default=0, ge=0, le=10_000)

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, value: str) -> str:
        normalized = value.strip()
        if not CHAT_ID_PATTERN.fullmatch(normalized):
            raise ValueError("chat_id must be @username or a negative Telegram chat ID")
        return normalized

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title is required")
        return normalized

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        normalized = value.strip()
        if not (normalized.startswith("https://t.me/") or normalized.startswith("tg://")):
            raise ValueError("url must be a Telegram link")
        return normalized


class SubscriptionChannelCreate(SubscriptionChannelPayload):
    admin_id: int = Field(gt=0)


class SubscriptionChannelUpdate(SubscriptionChannelPayload):
    admin_id: int = Field(gt=0)


class SubscriptionChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: str
    title: str
    url: str
    sort_order: int
