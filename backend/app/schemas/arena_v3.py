from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.arena_v3 import (
    ArenaV3AIReviewStatus,
    ArenaV3EvidenceStatus,
    ArenaV3SettlementStatus,
    ArenaV3Status,
)


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


class ArenaV3AppealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    match_id: int
    submitted_by: int | None
    reason_code: str
    comment: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None


class ArenaV3AppealDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Literal["ACCEPTED", "REJECTED"]
    owner_score: int | None = Field(default=None, ge=0, le=99)
    opponent_score: int | None = Field(default=None, ge=0, le=99)
    winner_player_id: int | None = Field(default=None, gt=0)
    admin_comment: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_accepted_result(self):
        if self.resolution == "ACCEPTED":
            if self.owner_score is None or self.opponent_score is None:
                raise ValueError("Accepted appeal requires both scores")
        elif any(
            value is not None
            for value in (self.owner_score, self.opponent_score, self.winner_player_id)
        ):
            raise ValueError("Rejected appeal must not include a match result")
        return self


class ArenaV3RankingPlayerResponse(BaseModel):
    player_id: int
    rank: int
    username: str
    wins: int
    losses: int
    draws: int
    total_matches: int
    win_rate: Decimal
    goals_for: int
    goals_against: int
    total_efc_won: Decimal


class ArenaV3RankingResponse(BaseModel):
    period: Literal["weekly", "monthly", "all"]
    players: list[ArenaV3RankingPlayerResponse]
    limit: int
    offset: int


class ArenaV3FoundationResponse(BaseModel):
    status: str
    detail: str


class ArenaV3MatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    public_id: str
    owner_id: int
    opponent_id: int | None
    owner_efootball_username: str
    opponent_efootball_username: str | None
    stake_efc: Decimal
    total_pool_efc: Decimal
    commission_efc: Decimal
    winner_reward_efc: Decimal
    match_type: str
    match_time_minutes: int
    extra_time_enabled: bool
    penalties_enabled: bool
    status: ArenaV3Status
    owner_ready_at: datetime | None
    opponent_ready_at: datetime | None
    room_code: str | None
    room_code_created_at: datetime | None
    playing_started_at: datetime | None
    settlement_status: ArenaV3SettlementStatus
    winner_id: int | None
    loser_id: int | None
    owner_score: int | None
    opponent_score: int | None
    result_source: str | None
    settled_at: datetime | None
    finished_at: datetime | None
    cancel_reason: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class ArenaV3MatchListResponse(BaseModel):
    matches: list[ArenaV3MatchResponse]


class ArenaV3ActiveMatchResponse(BaseModel):
    match: ArenaV3MatchResponse | None


class ArenaV3ScreenshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    match_id: int
    player_id: int
    mime_type: str
    file_size: int
    width: int
    height: int
    validation_status: ArenaV3EvidenceStatus
    uploaded_at: datetime


class ArenaV3ScreenshotListResponse(BaseModel):
    screenshots: list[ArenaV3ScreenshotResponse]


class ArenaV3AIReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    match_id: int
    status: ArenaV3AIReviewStatus
    owner_screenshot_id: int | None
    opponent_screenshot_id: int | None
    attempt_count: int
    winner_player_id: int | None = None
    score: str | None = None
    confidence: Decimal | None = None
    reason: str | None = None
    conflict_type: str | None = None
    model_name: str | None = None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ArenaV3ResultResponse(BaseModel):
    match: ArenaV3MatchResponse
    ai_review: ArenaV3AIReviewResponse | None


class ArenaV3ProfileResponse(BaseModel):
    player_id: int
    total_matches: int
    wins: int
    losses: int
    draws: int
    goals_for: int
    goals_against: int
    win_rate: Decimal
    current_streak: int
    best_streak: int
    total_efc_won: Decimal
    total_efc_lost: Decimal


class ArenaV3ConfigResponse(BaseModel):
    enabled: bool
    create_enabled: bool
    ai_enabled: bool
    settlement_enabled: bool
    match_time_minutes: list[int]
    penalties_required: bool
    room_code_max_length: int
    screenshot_deadline_seconds: int
