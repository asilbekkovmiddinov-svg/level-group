from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.tournament import (
    TournamentFormat,
    TournamentMatchStatus,
    TournamentParticipantStatus,
    TournamentStatus,
)


class TournamentCreate(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    format: TournamentFormat
    max_participants: int = Field(ge=2, le=128)
    ticket_cost: int = Field(default=1, ge=0, le=100)
    group_count: int | None = Field(default=None, ge=2, le=32)
    qualifiers_per_group: int | None = Field(default=None, ge=1, le=16)
    registration_opens_at: datetime
    registration_closes_at: datetime
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def validate_format_settings(self):
        if self.format == TournamentFormat.SINGLE_ELIMINATION:
            if self.group_count is not None or self.qualifiers_per_group is not None:
                raise ValueError("Olympic format cannot have group settings")
        elif self.group_count is None or self.qualifiers_per_group is None:
            raise ValueError("Group format requires group count and qualifiers")
        return self


class TournamentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    format: TournamentFormat
    status: TournamentStatus
    max_participants: int
    ticket_cost: int
    group_count: int | None
    qualifiers_per_group: int | None
    registration_opens_at: datetime
    registration_closes_at: datetime
    starts_at: datetime
    ends_at: datetime


class TournamentParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tournament_id: int
    telegram_id: int
    status: TournamentParticipantStatus
    seed: int | None
    group_name: str | None
    played: int
    wins: int
    losses: int
    points: int
    applied_at: datetime
    reviewed_at: datetime | None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class TournamentApplicationDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    seed: int | None = Field(default=None, ge=1)
    group_name: str | None = Field(default=None, max_length=16)


class TournamentMatchSchedule(BaseModel):
    player_a_id: int
    player_b_id: int
    round_number: int = Field(ge=1)
    round_name: str = Field(min_length=1, max_length=32)
    group_name: str | None = Field(default=None, max_length=16)
    scheduled_at: datetime


class TournamentMatchReschedule(BaseModel):
    scheduled_at: datetime


class TournamentMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tournament_id: int
    player_a_id: int
    player_b_id: int
    round_number: int
    round_name: str
    group_name: str | None
    scheduled_at: datetime
    status: TournamentMatchStatus
    arena_match_id: int | None
    player_a_ticket_state: str | None
    player_b_ticket_state: str | None
    winner_id: int | None
    player_a_score: int | None
    player_b_score: int | None


class TournamentOverviewResponse(BaseModel):
    tournament: TournamentResponse | None
    participant: TournamentParticipantResponse | None
    matches: list[TournamentMatchResponse] = []
