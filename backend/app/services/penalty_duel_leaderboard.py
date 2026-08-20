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
) -> list[dict]:
    weekly_results = _participant_results(db, mode, weekly_period_start(now))
    weekly_played = func.count(weekly_results.c.telegram_id)
    weekly_wins = func.sum(weekly_results.c.won)
    weekly_rating = RATING_BASE + weekly_wins * WIN_RATING_POINTS

    rows = (
        db.query(
            User,
            weekly_played.label("weekly_played"),
            weekly_wins.label("weekly_wins"),
            weekly_rating.label("weekly_rating"),
        )
        .join(weekly_results, weekly_results.c.telegram_id == User.telegram_id)
        .filter(User.telegram_id != AI_TELEGRAM_ID)
        .group_by(User.telegram_id)
        .order_by(
            weekly_rating.desc(),
            weekly_wins.desc(),
            weekly_played.asc(),
            User.telegram_id.asc(),
        )
        .limit(limit)
        .all()
    )

    player_ids = [user.telegram_id for user, *_ in rows]
    overall_by_player = {}
    if player_ids:
        overall_results = _participant_results(db, mode)
        overall_played = func.count(overall_results.c.telegram_id)
        overall_wins = func.sum(overall_results.c.won)
        overall_rows = (
            db.query(
                overall_results.c.telegram_id,
                overall_played.label("played"),
                overall_wins.label("wins"),
            )
            .filter(overall_results.c.telegram_id.in_(player_ids))
            .group_by(overall_results.c.telegram_id)
            .all()
        )
        overall_by_player = {
            telegram_id: (int(played or 0), int(wins or 0))
            for telegram_id, played, wins in overall_rows
        }

    result = []
    for rank, (user, games_played, games_won, player_rating) in enumerate(rows, start=1):
        weekly_games = int(games_played or 0)
        weekly_won = int(games_won or 0)
        overall_games, overall_won = overall_by_player.get(user.telegram_id, (0, 0))
        result.append({
            "rank": rank,
            "telegram_id": user.telegram_id,
            "display_name": _display_name(user),
            "username": user.username,
            "played": weekly_games,
            "wins": weekly_won,
            "losses": weekly_games - weekly_won,
            "rating": int(player_rating or 0),
            "weekly_played": weekly_games,
            "weekly_wins": weekly_won,
            "weekly_losses": weekly_games - weekly_won,
            "weekly_rating": int(player_rating or 0),
            "overall_played": overall_games,
            "overall_wins": overall_won,
            "overall_losses": overall_games - overall_won,
            "overall_rating": RATING_BASE + overall_won * WIN_RATING_POINTS,
        })
    return result
