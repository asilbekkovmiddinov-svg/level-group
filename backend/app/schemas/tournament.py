from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.tournament import (
    MAX_TOURNAMENT_PARTICIPANTS,
    TournamentEntryMode,
    TournamentFormat,
    TournamentGroupMode,
    TournamentMatchStatus,
    TournamentParticipantStatus,
    TournamentStatus,
)


class TournamentCreate(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    format: TournamentFormat = TournamentFormat.GROUP_PLAYOFF
    max_participants: int = Field(ge=4, le=MAX_TOURNAMENT_PARTICIPANTS)
    ticket_cost: int = Field(ge=0, le=1_000_000)
    entry_mode: TournamentEntryMode = TournamentEntryMode.TICKET
    minimum_coin_purchase: int = Field(default=300, ge=300, le=1_000_000)
    duration_days: int = Field(default=7, ge=1, le=365)
    auto_start_when_full: bool = False
    announcement_channel_id: str | None = Field(default=None, max_length=128)
    group_count: int | None = Field(default=None, ge=1, le=2048)
    group_size: Literal[4, 8] | None = None
    group_mode: TournamentGroupMode | None = None
    qualifiers_per_group: int | None = Field(default=None, ge=1, le=4)
    registration_opens_at: datetime
    registration_closes_at: datetime
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def validate_format_settings(self):
        channel = (self.announcement_channel_id or "").strip()
        if channel and not (
            channel.startswith("@")
            or channel.removeprefix("-").isdigit()
        ):
            raise ValueError("Channel must be a numeric chat ID or @username")
        self.announcement_channel_id = channel or None
        if (self.starts_at is None) != (self.ends_at is None):
            raise ValueError("Tournament start and end must be provided together")
        if self.starts_at is not None and self.ends_at is not None:
            if self.starts_at >= self.ends_at:
                raise ValueError("Tournament end must be after its start")
        if self.entry_mode == TournamentEntryMode.COIN_PURCHASE:
            self.auto_start_when_full = True
        if self.format == TournamentFormat.SINGLE_ELIMINATION:
            if any(value is not None for value in (
                self.group_count,
                self.group_size,
                self.group_mode,
                self.qualifiers_per_group,
            )):
                raise ValueError("Olympic format cannot have group settings")
        else:
            if self.group_size is None or self.group_mode is None:
                raise ValueError("Group size and group mode are required")
            if self.max_participants % self.group_size:
                raise ValueError("Participant count must be divisible by group size")
            if self.qualifiers_per_group is None:
                raise ValueError("Group qualifier count is required")
            if self.qualifiers_per_group >= self.group_size:
                raise ValueError("Group qualifiers must be fewer than group players")
            expected_groups = self.max_participants // self.group_size
            if self.group_count is not None and self.group_count != expected_groups:
                raise ValueError("Group count must match participant count and group size")
            self.group_count = expected_groups
        return self


class TournamentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    format: TournamentFormat
    status: TournamentStatus
    max_participants: int
    ticket_cost: int
    entry_mode: TournamentEntryMode
    minimum_coin_purchase: int
    duration_days: int
    auto_start_when_full: bool
    announcement_channel_id: str | None
    group_count: int | None
    group_size: int | None
    group_mode: TournamentGroupMode | None
    qualifiers_per_group: int | None
    registration_opens_at: datetime
    registration_closes_at: datetime
    starts_at: datetime | None
    ends_at: datetime | None


class TournamentParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tournament_id: int
    telegram_id: int
    status: TournamentParticipantStatus
    seed: int | None
    group_name: str | None
    entry_ticket_state: str | None
    qualification_order_id: int | None
    qualification_coin_amount: int | None
    played: int
    wins: int
    losses: int
    points: int
    goals_for: int
    goals_against: int
    advanced_round: int
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


class TournamentManualResult(BaseModel):
    player_a_score: int = Field(ge=0, le=99)
    player_b_score: int = Field(ge=0, le=99)

    @model_validator(mode="after")
    def reject_draw(self):
        if self.player_a_score == self.player_b_score:
            raise ValueError("Draw is not allowed; penalties are required")
        return self


class TournamentGroupFinalizeResponse(BaseModel):
    groups_finalized: int
    qualified_players: int
    eliminated_players: int


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
    tournament_tickets: int = Field(ge=0)
    participant_count: int = Field(default=0, ge=0)
    match_count: int = Field(default=0, ge=0)
    current_round: int = Field(default=0, ge=0)
    total_rounds: int = Field(default=0, ge=0)
    is_truncated: bool = False
    participants: list[TournamentParticipantResponse] = Field(default_factory=list)
    matches: list[TournamentMatchResponse] = Field(default_factory=list)
