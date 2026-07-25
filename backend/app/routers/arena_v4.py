from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.schemas.match import (
    ArenaDashboardResponse,
    ArenaLeaderboardResponse,
    ArenaProfileResponse,
)
from app.services import arena_v4


router = APIRouter(prefix="/arena", tags=["Arena V4"])


@router.get("/dashboard", response_model=ArenaDashboardResponse)
def get_arena_dashboard(
    _: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return {"stakes": arena_v4.get_dashboard(db)}


@router.get("/leaderboard", response_model=ArenaLeaderboardResponse)
def get_arena_leaderboard(
    period: Literal["weekly", "monthly", "all"] = Query(default="all"),
    limit: int = Query(default=100, ge=1, le=100),
    _: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return {
        "period": period,
        "users": arena_v4.get_leaderboard(db, period=period, limit=limit),
    }


@router.get("/profile", response_model=ArenaProfileResponse)
def get_arena_profile(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return arena_v4.get_profile(db, current_user.telegram_id)
