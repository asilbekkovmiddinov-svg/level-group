from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.models.match import MatchResultType, MatchStatus


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
    creator_telegram_id: int
    opponent_telegram_id: Optional[int]

    efc_amount: Decimal
    total_pool: Decimal
    commission_amount: Decimal
    winner_reward: Decimal

    status: MatchStatus

    scheduled_at: datetime
    ready_check_started_at: Optional[datetime]
    ready_check_deadline_at: Optional[datetime]

    creator_ready: bool
    opponent_ready: bool
    creator_ready_at: Optional[datetime]
    opponent_ready_at: Optional[datetime]

    room_code: Optional[str]
    room_code_created_by: Optional[int]
    room_code_created_at: Optional[datetime]

    creator_result_screenshot: Optional[str]
    opponent_result_screenshot: Optional[str]
    creator_result_uploaded_at: Optional[datetime]
    opponent_result_uploaded_at: Optional[datetime]

    winner_telegram_id: Optional[int]
    loser_telegram_id: Optional[int]
    result_type: Optional[MatchResultType]

    admin_telegram_id: Optional[int]
    admin_comment: Optional[str]
    resolved_at: Optional[datetime]

    cancel_reason: Optional[str]

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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


class MatchListResponse(BaseModel):
    matches: list[MatchResponse]


class MatchLeaderboardResponse(BaseModel):
    users: list[MatchStatsResponse]


class MatchGuideResponse(BaseModel):
    title: str
    text: str
