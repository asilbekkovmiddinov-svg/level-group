from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from app.models.match import Match, MatchStats, MatchStatus
from app.models.user import User
from app.services.arena_time import ensure_utc, utc_now


ARENA_V4_STAKES = (100, 500, 1000, 5000, 10000)
ONLINE_WINDOW = timedelta(minutes=5)
ACTIVE_STATUSES = (
    MatchStatus.WAITING_PLAYER,
    MatchStatus.WAITING_READY,
    MatchStatus.ROOM_READY,
    MatchStatus.PLAYING,
    MatchStatus.TECHNICAL_REVIEW,
    MatchStatus.WAITING_ADMIN,
)


def _period_start(period: Literal["weekly", "monthly", "all"], now: datetime) -> datetime | None:
    now = now.astimezone(timezone.utc)
    if period == "weekly":
        return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def get_dashboard(db: Session) -> list[dict]:
    now = utc_now()
    matches = db.execute(
        select(
            Match.efc_amount,
            Match.status,
            Match.creator_telegram_id,
            Match.opponent_telegram_id,
            Match.created_at,
        ).where(
            Match.efc_amount.in_(ARENA_V4_STAKES),
            Match.status.in_(ACTIVE_STATUSES),
        )
    ).all()
    participant_ids = {
        telegram_id
        for row in matches
        for telegram_id in (row.creator_telegram_id, row.opponent_telegram_id)
        if telegram_id is not None
    }
    online_ids = set()
    if participant_ids:
        online_ids = set(
            db.execute(
                select(User.telegram_id).where(
                    User.telegram_id.in_(participant_ids),
                    User.last_seen_at >= now - ONLINE_WINDOW,
                )
            ).scalars()
        )

    dashboard = []
    for stake in ARENA_V4_STAKES:
        stake_matches = [row for row in matches if Decimal(row.efc_amount) == Decimal(stake)]
        open_matches = [row for row in stake_matches if row.status == MatchStatus.WAITING_PLAYER]
        online_players = {
            telegram_id
            for row in stake_matches
            for telegram_id in (row.creator_telegram_id, row.opponent_telegram_id)
            if telegram_id in online_ids
        }
        wait_seconds = [
            max(0, int((now - ensure_utc(row.created_at)).total_seconds()))
            for row in open_matches
            if row.created_at is not None
        ]
        dashboard.append(
            {
                "stake": stake,
                "online_players": len(online_players),
                "open_rooms": len(open_matches),
                "average_wait_time": round(sum(wait_seconds) / len(wait_seconds)) if wait_seconds else 0,
            }
        )
    return dashboard


def get_profile(db: Session, telegram_id: int) -> dict:
    stats = db.query(MatchStats).filter(MatchStats.telegram_id == telegram_id).first()
    return {
        "total_matches": stats.total_matches if stats else 0,
        "wins": stats.wins if stats else 0,
        "losses": stats.losses if stats else 0,
        "win_rate": stats.win_rate if stats else Decimal("0"),
        "total_efc_won": stats.total_efc_won if stats else Decimal("0"),
        "current_streak": stats.win_streak if stats else 0,
        "best_streak": stats.best_win_streak if stats else 0,
    }


def get_leaderboard(
    db: Session,
    period: Literal["weekly", "monthly", "all"],
    limit: int,
) -> list[dict]:
    start = _period_start(period, utc_now())
    completed_filter = [
        Match.status == MatchStatus.COMPLETED,
        Match.winner_telegram_id.is_not(None),
        Match.loser_telegram_id.is_not(None),
    ]
    if start is not None:
        completed_filter.append(Match.resolved_at >= start)

    results = union_all(
        select(
            Match.winner_telegram_id.label("telegram_id"),
            literal(1).label("wins"),
            literal(0).label("losses"),
            Match.winner_reward.label("efc_won"),
        ).where(*completed_filter),
        select(
            Match.loser_telegram_id.label("telegram_id"),
            literal(0).label("wins"),
            literal(1).label("losses"),
            literal(0).label("efc_won"),
        ).where(*completed_filter),
    ).subquery()

    wins = func.sum(results.c.wins)
    losses = func.sum(results.c.losses)
    total_matches = wins + losses
    rows = db.execute(
        select(
            results.c.telegram_id,
            User.first_name,
            wins.label("wins"),
            losses.label("losses"),
            total_matches.label("total_matches"),
            func.sum(results.c.efc_won).label("total_efc_won"),
        )
        .join(User, User.telegram_id == results.c.telegram_id)
        .group_by(results.c.telegram_id, User.first_name)
        .order_by(wins.desc(), func.sum(results.c.efc_won).desc(), results.c.telegram_id.asc())
        .limit(limit)
    ).all()

    return [
        {
            "rank": index,
            "display_name": row.first_name or "O‘yinchi",
            "wins": int(row.wins or 0),
            "losses": int(row.losses or 0),
            "win_rate": (
                Decimal(row.wins or 0) * Decimal("100") / Decimal(row.total_matches)
                if row.total_matches
                else Decimal("0")
            ),
            "total_matches": int(row.total_matches or 0),
            "total_efc_won": Decimal(row.total_efc_won or 0),
        }
        for index, row in enumerate(rows, start=1)
    ]
