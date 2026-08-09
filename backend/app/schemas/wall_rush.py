from enum import Enum

from pydantic import BaseModel, Field

from app.models.wall_rush import WallRushMode


class ActionKind(str, Enum):
    MOVE = "MOVE"
    WALL = "WALL"


class JoinMatchRequest(BaseModel):
    mode: WallRushMode


class WallRushActionRequest(BaseModel):
    action: ActionKind
    row: int = Field(ge=0, le=12)
    column: int = Field(ge=0, le=8)
    orientation: str | None = None
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)


class MatchResponse(BaseModel):
    id: str
    mode: str
    status: str
    red_player_id: int
    blue_player_id: int | None
    current_turn_player_id: int | None
    red: tuple[int, int]
    blue: tuple[int, int]
    walls: list[dict]
    red_walls_remaining: int
    blue_walls_remaining: int
    red_missed_turns: int
    blue_missed_turns: int
    turn_number: int
    turn_deadline_at: object | None
    winner_id: int | None
    version: int


class TrustedAdRewardRequest(BaseModel):
    telegram_id: int = Field(gt=0)
    provider: str = Field(min_length=2, max_length=32)
    provider_event_id: str = Field(min_length=8, max_length=128)
