from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ArenaV3CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_efootball_username: str = Field(min_length=1, max_length=64)
    stake_efc: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    match_type: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9_]+$")
    match_time_minutes: int = Field(ge=6, le=15)
    extra_time_enabled: bool = False
    penalties_enabled: bool = True
    rules_accepted: bool

    @field_validator("owner_efootball_username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("eFootball username is required")
        return normalized

    @model_validator(mode="after")
    def validate_rules(self):
        if not self.penalties_enabled:
            raise ValueError("Penalties are mandatory")
        if not self.rules_accepted:
            raise ValueError("Arena rules must be accepted")
        return self


class ArenaV3JoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opponent_efootball_username: str = Field(min_length=1, max_length=64)
    rules_accepted: bool

    @model_validator(mode="after")
    def validate_rules(self):
        self.opponent_efootball_username = self.opponent_efootball_username.strip()
        if not self.opponent_efootball_username:
            raise ValueError("eFootball username is required")
        if not self.rules_accepted:
            raise ValueError("Arena rules must be accepted")
        return self


class ArenaV3ReadyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArenaV3RoomCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_code: str = Field(min_length=1, max_length=8)

    @field_validator("room_code")
    @classmethod
    def normalize_room_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 8:
            raise ValueError("Room code must contain 1-8 characters")
        return normalized


class ArenaV3CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")


class ArenaV3AppealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")
    comment: str | None = Field(default=None, max_length=500)


class ArenaV3FoundationResponse(BaseModel):
    status: str
    detail: str


class ArenaV3ConfigResponse(BaseModel):
    enabled: bool
    create_enabled: bool
    ai_enabled: bool
    settlement_enabled: bool
    match_time_minutes: list[int]
    penalties_required: bool
    room_code_max_length: int
    screenshot_deadline_seconds: int
