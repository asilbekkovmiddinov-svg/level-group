from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.division import DivisionParticipantStatus, DivisionSeasonStatus


class DivisionSeasonCreate(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    registration_opens_at: datetime
    registration_closes_at: datetime
    starts_at: datetime


class DivisionSeasonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: DivisionSeasonStatus
    duration_days: int
    ticket_cost: int
    points_for_win: int
    points_for_loss: int
    registration_opens_at: datetime
    registration_closes_at: datetime
    starts_at: datetime
    ends_at: datetime


class DivisionParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    season_id: int
    telegram_id: int
    status: DivisionParticipantStatus
    matches_played: int
    wins: int
    losses: int
    points: int
    goals_for: int
    goals_against: int
    applied_at: datetime
    reviewed_at: datetime | None


class DivisionOverviewResponse(BaseModel):
    season: DivisionSeasonResponse | None
    participant: DivisionParticipantResponse | None


class DivisionStandingEntry(BaseModel):
    rank: int
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    matches_played: int
    wins: int
    losses: int
    points: int
    goals_for: int
    goals_against: int
    goal_difference: int


class DivisionStandingsResponse(BaseModel):
    season: DivisionSeasonResponse
    items: list[DivisionStandingEntry]
    limit: int
    offset: int
    total: int


class DivisionApplicationListResponse(BaseModel):
    season: DivisionSeasonResponse
    items: list[DivisionParticipantResponse]
    limit: int
    offset: int
    total: int


class DivisionApplicationDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
