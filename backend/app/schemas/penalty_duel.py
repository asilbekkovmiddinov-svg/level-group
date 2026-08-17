from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.penalty_duel import PenaltyDuelMode


class PenaltyDirection(str, Enum):
    TOP_LEFT = "top-left"
    TOP_RIGHT = "top-right"
    CENTER = "center"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_RIGHT = "bottom-right"


class PenaltyDuelJoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: PenaltyDuelMode


class PenaltyDuelChoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: PenaltyDirection
    idempotency_key: str = Field(min_length=8, max_length=128)
