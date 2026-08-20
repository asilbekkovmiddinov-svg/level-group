from datetime import datetime, time, timedelta, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.penalty_duel import PenaltyDuelMatch, PenaltyDuelMode, PenaltyDuelStatus
from app.models.user import User
from app.services.penalty_duel import AI_TELEGRAM_ID

TASHKENT_TIMEZONE = timezone(timedelta(hours=5))
RATING_BASE = 1000
WIN_RATING_POINTS = 25


def _display_name(user: User) -> str:
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return name or user.username or str(user.telegram_id)


def weekly_period_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(TASHKENT_TIMEZONE)
    monday = local.date() - timedelta(days=local.weekday())
    return datetime.combine(monday, time.min, tzinfo=TASHKENT_TIMEZONE).astimezone(timezone.utc)


def weekly_period_end(now: datetime | None = None) -> datetime:
    return weekly_period_start(now) + timedelta(days=7)


def _participant_results(db: Session, mode: PenaltyDuelMode, since: datetime | None = None):
    common = (
        PenaltyDuelMatch.mode == mode,
        PenaltyDuelMatch.status == PenaltyDuelStatus.FINISHED,
        PenaltyDuelMatch.player_two_id.isnot(None),
        PenaltyDuelMatch.winner_id.isnot(None),
        PenaltyDuelMatch.finished_at.isnot(None),
    )
    if since is not None:
        common += (PenaltyDuelMatch.finished_at >= since,)

    # Include every finished match, including human-vs-AI, but never create
    # a leaderboard row for the AI participant itself.
    p1 = (
        db.query(
            PenaltyDuelMatch.player_one_id.label("telegram_id"),
            case((PenaltyDuelMatch.winner_id == PenaltyDuelMatch.player_one_id, 1), else_=0).label("won"),
        )
        .filter(*common, PenaltyDuelMatch.player_one_id != AI_TELEGRAM_ID)
    )
    p2 = (
        db.query(
            PenaltyDuelMatch.player_two_id.label("telegram_id"),
            case((PenaltyDuelMatch.winner_id == PenaltyDuelMatch.player_two_id, 1), else_=0).label("won"),
        )
        .filter(*common, PenaltyDuelMatch.player_two_id != AI_TELEGRAM_ID)
    )

    return p1.union_all(p2).subquery()


def leaderboard_rows(
    db: Session,
    mode: PenaltyDuelMode,
    limit: int = 20,
    now: datetime | None = None,
    period: str = "WEEKLY",
) -> list[dict]:
    normalized_period = period.upper()
    if normalized_period not in {"WEEKLY", "OVERALL"}:
        raise ValueError("Unsupported leaderboard period")
    since = weekly_period_start(now) if normalized_period == "WEEKLY" else None
    results = _participant_results(db, mode, since)
    played = func.count(results.c.telegram_id)
    wins = func.sum(results.c.won)
    rating = RATING_BASE + wins * WIN_RATING_POINTS

    rows = (
        db.query(
            User,
            played.label("played"),
            wins.label("wins"),
            rating.label("rating"),
        )
        .join(results, results.c.telegram_id == User.telegram_id)
        .filter(User.telegram_id != AI_TELEGRAM_ID)
        .group_by(User.telegram_id)
        .order_by(
            rating.desc(),
            wins.desc(),
            played.asc(),
            User.telegram_id.asc(),
        )
        .limit(limit)
        .all()
    )

    result = []
    for rank, (user, games_played, games_won, player_rating) in enumerate(rows, start=1):
        games = int(games_played or 0)
        won = int(games_won or 0)
        row = {
            "rank": rank,
            "telegram_id": user.telegram_id,
            "display_name": _display_name(user),
            "username": user.username,
            "period": normalized_period,
            "played": games,
            "wins": won,
            "losses": games - won,
            "rating": int(player_rating or 0),
        }
        prefix = normalized_period.lower()
        row.update({
            f"{prefix}_played": games,
            f"{prefix}_wins": won,
            f"{prefix}_losses": games - won,
            f"{prefix}_rating": int(player_rating or 0),
        })
        result.append(row)
    return result
