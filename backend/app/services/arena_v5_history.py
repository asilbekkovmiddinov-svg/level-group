from __future__ import annotations

from sqlalchemy import or_, select

from app.models.arena_v3 import ArenaV3Match, ArenaV3Status


def get_arena_v5_history(
    db,
    player_id: int,
    *,
    limit: int,
    offset: int,
    season_id: int | None = None,
) -> list[dict]:
    """Return only complete Arena V5 results.

    Legacy/incomplete FINISHED rows may have a NULL score.  They must not make
    the whole history endpoint fail while comparing scores.
    """
    filters = [
        ArenaV3Match.flow_version == 5,
        ArenaV3Match.status == ArenaV3Status.FINISHED,
        ArenaV3Match.owner_score.is_not(None),
        ArenaV3Match.opponent_score.is_not(None),
        or_(
            ArenaV3Match.owner_id == player_id,
            ArenaV3Match.opponent_id == player_id,
        ),
    ]
    if season_id is not None:
        filters.append(ArenaV3Match.arena_v5_season_id == season_id)
    matches = db.execute(
        select(ArenaV3Match)
        .where(*filters)
        .order_by(ArenaV3Match.finished_at.desc(), ArenaV3Match.id.desc())
        .offset(offset)
        .limit(limit)
    ).scalars().all()

    items: list[dict] = []
    for match in matches:
        is_owner = match.owner_id == player_id
        own_score = match.owner_score if is_owner else match.opponent_score
        opponent_score = match.opponent_score if is_owner else match.owner_score
        if own_score > opponent_score:
            result, points = "WIN", 3
        elif own_score == opponent_score:
            result, points = "DRAW", 1
        else:
            result, points = "LOSS", 0
        items.append({
            "match_id": match.id,
            "season_id": match.arena_v5_season_id,
            "public_id": match.public_id,
            "opponent_efootball_username": (
                match.opponent_efootball_username
                if is_owner else match.owner_efootball_username
            ),
            "own_score": own_score,
            "opponent_score": opponent_score,
            "result": result,
            "points": points,
            "finished_at": match.finished_at,
        })
    return items
