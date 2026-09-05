from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArenaV5ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    efootball_username: str = Field(min_length=1, max_length=64)

    @field_validator("efootball_username")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("eFootball username is required")
        return normalized


class ArenaV5PromocodeClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=32)


class ArenaV5PromocodeClaimResponse(BaseModel):
    code: str
    ticket_amount: int
    ticket_balance: int


class ArenaV5ProfileResponse(BaseModel):
    telegram_id: int
    telegram_username: str | None
    efootball_username: str | None
    season_id: int | None
    games_played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    goal_difference: int
    match_points: int
    referral_points: int
    referral_count: int
    points: int


class ArenaV5PlayerResponse(BaseModel):
    telegram_id: int
    telegram_username: str | None
    efootball_username: str


class ArenaV5MatchResponse(BaseModel):
    id: int
    public_id: str
    status: str
    player_a: ArenaV5PlayerResponse
    player_b: ArenaV5PlayerResponse | None
    score_a: int | None
    score_b: int | None
    bot_deep_link: str | None
    created_at: datetime
    finished_at: datetime | None
    legacy_flow: bool = False


class ArenaV5StateResponse(BaseModel):
    state: Literal["IDLE", "SEARCHING", "MATCHED"]
    ticket_balance: int
    queued_at: datetime | None = None
    match: ArenaV5MatchResponse | None = None


class ArenaV5QueueResponse(ArenaV5StateResponse):
    matched_now: bool = False


class ArenaV5HistoryItem(BaseModel):
    match_id: int
    season_id: int | None
    public_id: str
    opponent_efootball_username: str
    own_score: int
    opponent_score: int
    result: Literal["WIN", "DRAW", "LOSS"]
    points: int
    finished_at: datetime


class ArenaV5SeasonHistoryItem(BaseModel):
    season_id: int
    season_name: str
    season_status: Literal["ACTIVE", "FINISHED"]
    season_start_at: datetime
    season_end_at: datetime
    games_played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    goal_difference: int
    match_points: int
    referral_count: int
    referral_points: int
    points: int


class ArenaV5RankingItem(BaseModel):
    rank: int
    telegram_id: int
    efootball_username: str
    games_played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    goal_difference: int
    match_points: int
    referral_points: int
    referral_count: int
    points: int


class ArenaV5RankingResponse(BaseModel):
    season_id: int | None
    season_status: Literal["ACTIVE", "FINISHED", "CLOSED"]
    season_name: str | None
    season_start_at: datetime | None
    season_end_at: datetime | None
    prize_text: str | None
    players: list[ArenaV5RankingItem]


class ArenaV5ConfigResponse(BaseModel):
    ticket_cost: int
    ticket_balance: int
    season_id: int | None
    season_status: Literal["ACTIVE", "CLOSED"]
    season_name: str | None
    season_start_at: datetime | None
    season_end_at: datetime | None
    duration_days: int | None
    prize_text: str | None
    points_for_win: int
    points_for_draw: int
    points_for_loss: int
    referral_points: int


class ArenaV5SeasonResponse(BaseModel):
    id: int
    name: str
    status: Literal["ACTIVE", "FINISHED"]
    duration_days: int
    starts_at: datetime
    ends_at: datetime
    finished_at: datetime | None
    prize_text: str | None
    points_for_win: int
    points_for_draw: int
    points_for_loss: int
    referral_points: int
    match_count: int
    referral_count: int


class ArenaV5SeasonListResponse(BaseModel):
    seasons: list[ArenaV5SeasonResponse]


class ArenaV5SeasonCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    duration_days: int = Field(ge=1, le=365)
    prize_text: str | None = Field(default=None, max_length=500)
    admin_id: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def normalize_season_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Arena season name is required")
        return normalized


class ArenaV5SeasonFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admin_id: int = Field(gt=0)


class ArenaV5SeasonDurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration_days: int = Field(ge=1, le=365)
    admin_id: int = Field(gt=0)


class ArenaV5RelayValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_id: int = Field(gt=0)
    token: str = Field(min_length=16, max_length=64)


class ArenaV5ActiveMatchInternalResponse(BaseModel):
    match: ArenaV5MatchResponse | None
    opponent_telegram_id: int | None = None
    relay_allowed: bool = False


class ArenaV5SubmissionPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_id: int = Field(gt=0)
    telegram_file_id: str = Field(min_length=1, max_length=500)
    telegram_message_id: int = Field(gt=0)


class ArenaV5SubmissionCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admin_channel_message_id: int = Field(gt=0)


class ArenaV5SubmissionFailedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: str = Field(min_length=1, max_length=255)


class ArenaV5SubmissionResponse(BaseModel):
    submission_id: int
    delivery_status: str
    should_deliver: bool
    match: ArenaV5MatchResponse
    submitted_by: ArenaV5PlayerResponse
