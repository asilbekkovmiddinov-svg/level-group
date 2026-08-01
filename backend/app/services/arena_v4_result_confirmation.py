from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.models.arena_v3 import (
    ArenaV3MatchEvent,
    ArenaV3Status,
    ArenaV4RewardHoldStatus,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3 import (
    ArenaV3Conflict,
    ArenaV3Forbidden,
    ArenaV3NotFound,
)
from app.services.arena_v4_reward_release import release_match_reward


def confirm_result(
    db,
    *,
    match_id: int,
    player_id: int,
    idempotency_key: str,
    now=None,
):
    now = now or datetime.now(timezone.utc)
    repository = ArenaV3Repository(db)
    match = repository.get_match_for_update(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V4 match not found")
    if player_id not in {match.owner_id, match.opponent_id}:
        raise ArenaV3Forbidden("Player is not a match participant")

    event_key = f"v4-result-confirm:{player_id}:{idempotency_key}"
    previous = repository.get_event_by_idempotency(match.id, event_key)
    if previous is not None:
        response = _response(match, player_id, reward_released=False)
        db.rollback()
        return response
    if match.status != ArenaV3Status.FINISHED:
        raise ArenaV3Conflict("Only a finished result can be confirmed")
    if match.has_appeal or repository.get_appeal_for_update(match.id) is not None:
        raise ArenaV3Conflict("Result confirmation is blocked by an appeal")
    if match.reward_hold_status != ArenaV4RewardHoldStatus.LOCKED:
        raise ArenaV3Conflict("Arena reward is not awaiting confirmation")

    field = (
        "owner_result_confirmed_at"
        if player_id == match.owner_id
        else "opponent_result_confirmed_at"
    )
    if getattr(match, field) is not None:
        response = _response(match, player_id, reward_released=False)
        db.rollback()
        return response
    setattr(match, field, now)
    repository.add_event(ArenaV3MatchEvent(
        match_id=match.id,
        event_type="V4_RESULT_CONFIRMED",
        from_status=match.status.value,
        to_status=match.status.value,
        actor_type="USER",
        actor_id=player_id,
        idempotency_key=event_key,
        event_metadata={"result_version": match.result_version},
    ))

    both_confirmed = bool(
        match.owner_result_confirmed_at
        and match.opponent_result_confirmed_at
    )
    try:
        if both_confirmed:
            match.reward_release_at = now
            match.appeal_deadline_at = now
            released = release_match_reward(
                db, match.id, now=now, force=True
            )
            if released.outcome not in {"RELEASED", "ALREADY_RELEASED"}:
                raise ArenaV3Conflict("Arena reward could not be released")
            return _response(match, player_id, reward_released=True)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ArenaV3Conflict("Arena result confirmation already exists") from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(match)
    return _response(match, player_id, reward_released=False)


def _response(match, player_id: int, *, reward_released: bool):
    owner_confirmed = match.owner_result_confirmed_at is not None
    opponent_confirmed = match.opponent_result_confirmed_at is not None
    return {
        "match_id": match.id,
        "confirmed_by": player_id,
        "owner_confirmed": owner_confirmed,
        "opponent_confirmed": opponent_confirmed,
        "both_confirmed": owner_confirmed and opponent_confirmed,
        "reward_hold_status": match.reward_hold_status,
        "reward_released": reward_released,
    }
