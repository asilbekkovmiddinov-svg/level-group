from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func, literal, select, union_all

from app.models.arena_v3 import ArenaV3Match, ArenaV3Stats, ArenaV3Status
from app.models.user import User


def _period_start(period: str, now: datetime):
    if period == "weekly":
        return now - timedelta(days=7)
    if period == "monthly":
        return now - timedelta(days=30)
    return None


def _username(user) -> str:
    if user is None:
        return "O‘yinchi"
    return user.username or user.first_name or "O‘yinchi"


def _all_time(db, *, limit: int, offset: int):
    rows = db.execute(
        select(ArenaV3Stats, User)
        .join(User, User.telegram_id == ArenaV3Stats.player_id)
        .where(ArenaV3Stats.total_matches > 0)
        .order_by(
            ArenaV3Stats.wins.desc(),
            ArenaV3Stats.win_rate.desc(),
            (ArenaV3Stats.goals_for - ArenaV3Stats.goals_against).desc(),
            ArenaV3Stats.player_id.asc(),
        )
        .offset(offset).limit(limit)
    ).all()
    return [
        {
            "player_id": stats.player_id,
            "rank": offset + index,
            "username": _username(user),
            "wins": stats.wins,
            "losses": stats.losses,
            "draws": stats.draws,
            "total_matches": stats.total_matches,
            "win_rate": stats.win_rate,
            "goals_for": stats.goals_for,
            "goals_against": stats.goals_against,
            "total_efc_won": stats.total_efc_won,
        }
        for index, (stats, user) in enumerate(rows, start=1)
    ]


def _periodic(db, *, period: str, limit: int, offset: int, now: datetime):
    start = _period_start(period, now)
    filters = (
        ArenaV3Match.status == ArenaV3Status.FINISHED,
        ArenaV3Match.finished_at >= start,
        ArenaV3Match.owner_score.is_not(None),
        ArenaV3Match.opponent_score.is_not(None),
    )
    owner = select(
        ArenaV3Match.owner_id.label("player_id"),
        case((ArenaV3Match.winner_id == ArenaV3Match.owner_id, 1), else_=0).label("wins"),
        case((ArenaV3Match.winner_id == ArenaV3Match.opponent_id, 1), else_=0).label("losses"),
        case((ArenaV3Match.winner_id.is_(None), 1), else_=0).label("draws"),
        ArenaV3Match.owner_score.label("goals_for"),
        ArenaV3Match.opponent_score.label("goals_against"),
        case(
            (
                ArenaV3Match.winner_id == ArenaV3Match.owner_id,
                ArenaV3Match.winner_reward_efc - ArenaV3Match.stake_efc,
            ),
            else_=literal(0),
        ).label("efc_won"),
    ).where(*filters)
    opponent = select(
        ArenaV3Match.opponent_id.label("player_id"),
        case((ArenaV3Match.winner_id == ArenaV3Match.opponent_id, 1), else_=0).label("wins"),
        case((ArenaV3Match.winner_id == ArenaV3Match.owner_id, 1), else_=0).label("losses"),
        case((ArenaV3Match.winner_id.is_(None), 1), else_=0).label("draws"),
        ArenaV3Match.opponent_score.label("goals_for"),
        ArenaV3Match.owner_score.label("goals_against"),
        case(
            (
                ArenaV3Match.winner_id == ArenaV3Match.opponent_id,
                ArenaV3Match.winner_reward_efc - ArenaV3Match.stake_efc,
            ),
            else_=literal(0),
        ).label("efc_won"),
    ).where(*filters, ArenaV3Match.opponent_id.is_not(None))
    results = union_all(owner, opponent).subquery()
    wins = func.sum(results.c.wins)
    losses = func.sum(results.c.losses)
    draws = func.sum(results.c.draws)
    total = wins + losses + draws
    rows = db.execute(
        select(
            results.c.player_id,
            User,
            wins.label("wins"),
            losses.label("losses"),
            draws.label("draws"),
            total.label("total_matches"),
            func.sum(results.c.goals_for).label("goals_for"),
            func.sum(results.c.goals_against).label("goals_against"),
            func.sum(results.c.efc_won).label("total_efc_won"),
        )
        .join(User, User.telegram_id == results.c.player_id)
        .join(ArenaV3Stats, ArenaV3Stats.player_id == results.c.player_id)
        .group_by(results.c.player_id, User.telegram_id)
        .order_by(
            wins.desc(),
            (func.sum(results.c.goals_for) - func.sum(results.c.goals_against)).desc(),
            results.c.player_id.asc(),
        )
        .offset(offset).limit(limit)
    ).all()
    return [
        {
            "player_id": row.player_id,
            "rank": offset + index,
            "username": _username(row.User),
            "wins": int(row.wins or 0),
            "losses": int(row.losses or 0),
            "draws": int(row.draws or 0),
            "total_matches": int(row.total_matches or 0),
            "win_rate": (
                Decimal(row.wins or 0) * Decimal("100") / Decimal(row.total_matches)
            ).quantize(Decimal("0.01")) if row.total_matches else Decimal("0"),
            "goals_for": int(row.goals_for or 0),
            "goals_against": int(row.goals_against or 0),
            "total_efc_won": Decimal(row.total_efc_won or 0),
        }
        for index, row in enumerate(rows, start=1)
    ]


def get_ranking(
    db,
    *,
    period: str,
    limit: int,
    offset: int,
    now: datetime | None = None,
):
    if period not in {"weekly", "monthly", "all"}:
        raise ValueError("Unsupported Arena V3 ranking period")
    if period == "all":
        return _all_time(db, limit=limit, offset=offset)
    return _periodic(
        db, period=period, limit=limit, offset=offset,
        now=now or datetime.now(timezone.utc),
    )
