from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.models.match import MatchGameType, MatchResultType, MatchStatus


class MatchCreate(BaseModel):
    creator_telegram_id: int
    efc_amount: Decimal
    scheduled_at: datetime


class MatchAccept(BaseModel):
    opponent_telegram_id: int


class MatchReady(BaseModel):
    telegram_id: int


class MatchRoomCodeCreate(BaseModel):
    telegram_id: int
    room_code: str


class MatchScreenshotUpload(BaseModel):
    telegram_id: int
    screenshot_file_id: str


class MatchAdminResolve(BaseModel):
    admin_telegram_id: int
    winner_telegram_id: int
    admin_comment: Optional[str] = None


class MatchCancel(BaseModel):
    admin_telegram_id: Optional[int] = None
    cancel_reason: str


class MatchResponse(BaseModel):
    id: int

    game_type: MatchGameType
    creator_display_name: str
    opponent_display_name: str

    efc_amount: Decimal
    total_pool: Decimal
    winner_reward: Decimal

    status: MatchStatus
    scheduled_at: datetime

    ready_window_started_at: Optional[datetime] = None
    ready_deadline_at: Optional[datetime] = None

    creator_ready: bool
    opponent_ready: bool
    result_type: Optional[MatchResultType] = None
    resolved_at: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MatchInternalResponse(BaseModel):
    """Admin/internal-only representation. Never use for public endpoints."""

    id: int
    game_type: MatchGameType
    creator_telegram_id: int
    creator_username: Optional[str] = None
    creator_first_name: Optional[str] = None
    opponent_telegram_id: Optional[int] = None
    opponent_username: Optional[str] = None
    opponent_first_name: Optional[str] = None

    efc_amount: Decimal
    total_pool: Decimal
    commission_amount: Decimal
    winner_reward: Decimal
    status: MatchStatus
    scheduled_at: datetime

    ready_window_started_at: Optional[datetime] = None
    ready_deadline_at: Optional[datetime] = None
    creator_ready: bool
    opponent_ready: bool
    creator_ready_at: Optional[datetime] = None
    opponent_ready_at: Optional[datetime] = None
    creator_rules_accepted_at: Optional[datetime] = None
    opponent_rules_accepted_at: Optional[datetime] = None

    room_code: Optional[str] = None
    room_code_created_by: Optional[int] = None
    room_code_created_at: Optional[datetime] = None

    creator_result_screenshot: Optional[str] = None
    opponent_result_screenshot: Optional[str] = None
    creator_result_uploaded_at: Optional[datetime] = None
    opponent_result_uploaded_at: Optional[datetime] = None
    creator_result_video: Optional[str] = None
    opponent_result_video: Optional[str] = None
    creator_result_video_uploaded_at: Optional[datetime] = None
    opponent_result_video_uploaded_at: Optional[datetime] = None
    creator_evidence_complete: bool
    opponent_evidence_complete: bool

    winner_telegram_id: Optional[int] = None
    loser_telegram_id: Optional[int] = None
    result_type: Optional[MatchResultType] = None
    admin_telegram_id: Optional[int] = None
    admin_comment: Optional[str] = None
    resolved_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MatchListResponse(BaseModel):
    matches: list[MatchResponse]


class MatchStatsResponse(BaseModel):
    id: int
    telegram_id: int

    total_matches: int
    wins: int
    losses: int
    win_rate: Decimal
    win_streak: int
    best_win_streak: int

    total_efc_won: Decimal
    total_efc_lost: Decimal
    biggest_win: Decimal

    rating: int

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MatchLeaderboardResponse(BaseModel):
    users: list[MatchStatsResponse]


class MatchGuideResponse(BaseModel):
    title: str
    text: str
