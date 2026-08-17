from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.penalty_duel import PenaltyDuelMatch, PenaltyDuelMode, PenaltyDuelStatus
from app.models.user import User
from app.services.penalty_duel import AI_TELEGRAM_ID


def _display_name(user: User) -> str:
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return name or user.username or str(user.telegram_id)


def leaderboard_rows(db: Session, mode: PenaltyDuelMode, limit: int = 20) -> list[dict]:
    common = (
        PenaltyDuelMatch.mode == mode,
        PenaltyDuelMatch.status == PenaltyDuelStatus.FINISHED,
        PenaltyDuelMatch.player_two_id.isnot(None),
        PenaltyDuelMatch.winner_id.isnot(None),
    )

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

    results = p1.union_all(p2).subquery()
    played = func.count(results.c.telegram_id)
    wins = func.sum(results.c.won)
    rating = 1000 + wins * 25

    rows = (
        db.query(User, played.label("played"), wins.label("wins"), rating.label("rating"))
        .join(results, results.c.telegram_id == User.telegram_id)
        .filter(User.telegram_id != AI_TELEGRAM_ID)
        .group_by(User.telegram_id)
        .order_by(rating.desc(), wins.desc(), played.asc(), User.telegram_id.asc())
        .limit(limit)
        .all()
    )

    return [
        {
            "rank": rank,
            "telegram_id": user.telegram_id,
            "display_name": _display_name(user),
            "username": user.username,
            "played": int(games_played or 0),
            "wins": int(games_won or 0),
            "losses": int(games_played or 0) - int(games_won or 0),
            "rating": int(player_rating or 0),
        }
        for rank, (user, games_played, games_won, player_rating) in enumerate(rows, start=1)
    ]
