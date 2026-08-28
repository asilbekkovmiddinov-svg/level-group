from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArenaPromocodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=32)
    ticket_amount: int = Field(gt=0, le=10000)
    usage_limit: int | None = Field(default=None, gt=0, le=1_000_000)
    expires_at: datetime | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = "".join(value.strip().upper().split())
        if not normalized:
            raise ValueError("Promocode is required")
        if not all(
            character.isascii() and (character.isalnum() or character in "-_")
            for character in normalized
        ):
            raise ValueError("Promocode may contain only A-Z, 0-9, hyphen and underscore")
        return normalized


class ArenaPromocodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    ticket_amount: int
    usage_limit: int | None
    usage_count: int
    is_active: bool
    expires_at: datetime | None
    created_by: int
    created_at: datetime
