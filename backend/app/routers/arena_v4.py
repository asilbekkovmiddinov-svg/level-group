from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import inspect

from app.core import config
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.schemas.arena_v3 import ArenaV3ProfileResponse
from app.models.arena_v3 import ArenaV3Appeal, ArenaV3AppealStatus
from app.models.wallet import Wallet
from app.schemas.match import (
    ArenaDashboardResponse,
    ArenaLeaderboardResponse,
    ArenaProfileResponse,
)
from app.services import arena_v4
from app.services.arena_v3 import ArenaV3Service


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


@router.get(
    "/profile",
    response_model=ArenaV3ProfileResponse | ArenaProfileResponse,
)
def get_arena_profile(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    if (
        (
            config.ARENA_V3_ENABLED
            or current_user.telegram_id in config.ARENA_V3_ALLOWED_TELEGRAM_IDS
        )
        and inspect(db.get_bind()).has_table("arena_stats_v3")
    ):
        stats = ArenaV3Service(db).profile(player_id=current_user.telegram_id)
        wallet = db.query(Wallet).filter(
            Wallet.telegram_id == current_user.telegram_id
        ).first()
        pending_appeals = db.query(ArenaV3Appeal).filter(
            ArenaV3Appeal.submitted_by == current_user.telegram_id,
            ArenaV3Appeal.status.in_([
                ArenaV3AppealStatus.PENDING,
                ArenaV3AppealStatus.UNDER_REVIEW,
            ]),
        ).count()
        if stats is not None:
            return {
                column.name: getattr(stats, column.name)
                for column in stats.__table__.columns
                if column.name in ArenaV3ProfileResponse.model_fields
            } | {
                "locked_rewards_efc": (
                    wallet.locked_reward_efc if wallet else 0
                ),
                "pending_appeals": pending_appeals,
            }
        return {
            "player_id": current_user.telegram_id,
            "total_matches": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "goals_for": 0,
            "goals_against": 0,
            "win_rate": 0,
            "current_streak": 0,
            "best_streak": 0,
            "total_efc_won": 0,
            "total_efc_lost": 0,
            "locked_rewards_efc": wallet.locked_reward_efc if wallet else 0,
            "pending_appeals": pending_appeals,
        }
    return arena_v4.get_profile(db, current_user.telegram_id)
