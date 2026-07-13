from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user

router = APIRouter(prefix="/matches", tags=["1vs1 Arena Overview"])


@router.get("/overview")
def get_match_overview(
    _: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)
    online_limit = now - timedelta(minutes=5)

    online_users = db.execute(
        text("""
            SELECT COUNT(*)
            FROM users
            WHERE last_seen_at >= :online_limit
        """),
        {"online_limit": online_limit},
    ).scalar() or 0

    open_matches = db.execute(
        text("""
            SELECT COUNT(*)
            FROM matches
            WHERE status = 'WAITING_PLAYER'
        """)
    ).scalar() or 0

    active_matches = db.execute(
        text("""
            SELECT COUNT(*)
            FROM matches
            WHERE status IN (
                'SCHEDULED',
                'READY_CHECK',
                'WAITING_ROOM_CODE',
                'MATCH_STARTED',
                'WAITING_ADMIN',
                'TECHNICAL_WIN'
            )
        """)
    ).scalar() or 0

    today_completed_matches = db.execute(
        text("""
            SELECT COUNT(*)
            FROM matches
            WHERE status = 'COMPLETED'
            AND resolved_at >= :today_start
        """),
        {"today_start": today_start},
    ).scalar() or 0

    today_efc_pool = db.execute(
        text("""
            SELECT COALESCE(SUM(total_pool), 0)
            FROM matches
            WHERE status = 'COMPLETED'
            AND resolved_at >= :today_start
        """),
        {"today_start": today_start},
    ).scalar() or 0

    total_completed_matches = db.execute(
        text("""
            SELECT COUNT(*)
            FROM matches
            WHERE status = 'COMPLETED'
        """)
    ).scalar() or 0

    total_efc_pool = db.execute(
        text("""
            SELECT COALESCE(SUM(total_pool), 0)
            FROM matches
            WHERE status = 'COMPLETED'
        """)
    ).scalar() or 0

    return {
        "online_users": int(online_users),
        "open_matches": int(open_matches),
        "active_matches": int(active_matches),
        "today_completed_matches": int(today_completed_matches),
        "today_efc_pool": float(today_efc_pool),
        "total_completed_matches": int(total_completed_matches),
        "total_efc_pool": float(total_efc_pool),
    }
