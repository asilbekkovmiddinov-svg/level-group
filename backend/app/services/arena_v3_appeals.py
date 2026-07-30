from __future__ import annotations

from datetime import datetime, timezone

from app.models.arena_v3 import (
    ArenaV3AIReviewStatus,
    ArenaV3Appeal,
    ArenaV3AppealStatus,
    ArenaV3MatchEvent,
    ArenaV3Status,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3 import (
    ArenaV3Conflict,
    ArenaV3Forbidden,
    ArenaV3NotFound,
)
from app.services.arena_v3_state_machine import transition_arena_v3


def _event(repository, match, event_type, key, *, actor_type, actor_id, metadata=None):
    existing = repository.get_event_by_idempotency(match.id, key)
    if existing:
        return existing
    event = ArenaV3MatchEvent(
        match_id=match.id,
        event_type=event_type,
        from_status=ArenaV3Status(match.status).value,
        to_status=ArenaV3Status(match.status).value,
        actor_type=actor_type,
        actor_id=actor_id,
        idempotency_key=key,
        event_metadata=metadata,
    )
    repository.add_event(event)
    return event


def ensure_video_upload_allowed(
    db, *, match_id: int, player_id: int, idempotency_key: str
):
    repository = ArenaV3Repository(db)
    match = repository.get_match(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V3 match not found")
    previous = repository.get_appeal_by_idempotency(match.id, idempotency_key)
    if previous is not None:
        appeal = repository.get_appeal_for_update(match.id)
        if previous.actor_id != player_id or appeal is None:
            raise ArenaV3Conflict("Idempotency key belongs to another appeal")
        return appeal
    if player_id not in {match.owner_id, match.opponent_id}:
        raise ArenaV3Forbidden("Player is not a match participant")
    review = repository.get_latest_ai_review(match.id)
    if (
        match.status != ArenaV3Status.AI_REVIEW
        or review is None
        or review.status != ArenaV3AIReviewStatus.APPEAL_REQUIRED
    ):
        raise ArenaV3Conflict("Arena V3 match does not require an appeal")
    appeal = repository.get_open_appeal(match.id)
    if appeal is not None and appeal.submitted_by is not None:
        raise ArenaV3Conflict("Arena V3 appeal video was already submitted")
    return None


def submit_video_appeal(
    db,
    *,
    match_id: int,
    player_id: int,
    payload,
    idempotency_key: str,
    storage_key: str,
    file_hash: str,
):
    repository = ArenaV3Repository(db)
    match = repository.get_match_for_update(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V3 match not found")
    previous = repository.get_appeal_by_idempotency(match.id, idempotency_key)
    appeal = repository.get_appeal_for_update(match.id)
    if previous is not None:
        if previous.actor_id != player_id or appeal is None:
            raise ArenaV3Conflict("Idempotency key belongs to another appeal")
        return appeal
    if player_id not in {match.owner_id, match.opponent_id}:
        raise ArenaV3Forbidden("Player is not a match participant")
    review = repository.get_latest_ai_review(match.id)
    if (
        match.status != ArenaV3Status.AI_REVIEW
        or review is None
        or review.status != ArenaV3AIReviewStatus.APPEAL_REQUIRED
    ):
        raise ArenaV3Conflict("Arena V3 match does not require an appeal")
    if appeal is None:
        appeal = repository.add_appeal(ArenaV3Appeal(
            match_id=match.id,
            reason_code=payload.reason_code,
            status=ArenaV3AppealStatus.OPEN,
        ))
    if (
        appeal.submitted_by is not None
        or appeal.status != ArenaV3AppealStatus.OPEN
        or appeal.video_storage_key is not None
    ):
        raise ArenaV3Conflict("Arena V3 appeal video was already submitted")
    appeal.submitted_by = player_id
    appeal.reason_code = payload.reason_code
    appeal.comment = payload.comment
    appeal.video_storage_key = storage_key
    appeal.file_hash = file_hash
    appeal.status = ArenaV3AppealStatus.SUBMITTED
    _event(
        repository, match, "APPEAL_VIDEO_UPLOADED",
        f"appeal-upload:{idempotency_key}",
        actor_type="USER", actor_id=player_id,
        metadata={"appeal_id": appeal.id},
    )
    appeal.status = ArenaV3AppealStatus.UNDER_REVIEW
    _event(
        repository, match, "APPEAL_WAITING_ADMIN",
        f"appeal-waiting-admin:{appeal.id}",
        actor_type="SYSTEM", actor_id=None,
        metadata={"appeal_id": appeal.id},
    )
    db.commit()
    db.refresh(appeal)
    return appeal


def resolve_appeal(db, *, match_id: int, payload, idempotency_key: str):
    repository = ArenaV3Repository(db)
    match = repository.get_match_for_update(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V3 match not found")
    appeal = repository.get_appeal_for_update(match.id)
    if appeal is None:
        raise ArenaV3NotFound("Arena V3 appeal not found")
    event_key = f"appeal-decision:{idempotency_key}"
    previous = repository.get_event_by_idempotency(match.id, event_key)
    if previous is not None:
        return match
    if (
        match.status != ArenaV3Status.AI_REVIEW
        or appeal.status != ArenaV3AppealStatus.UNDER_REVIEW
    ):
        raise ArenaV3Conflict("Arena V3 appeal is not awaiting admin review")
    review = repository.get_latest_ai_review(match.id)
    if review is None or review.status != ArenaV3AIReviewStatus.APPEAL_REQUIRED:
        raise ArenaV3Conflict("Arena V3 conflict result is missing")

    appeal.admin_comment = payload.admin_comment
    appeal.resolution = payload.resolution
    appeal.resolved_at = datetime.now(timezone.utc)
    if payload.resolution == "REJECTED":
        appeal.status = ArenaV3AppealStatus.REJECTED
        transition_arena_v3(match, ArenaV3Status.CANCELLED)
        match.cancel_reason = "APPEAL_REJECTED"
        _event(
            repository, match, "APPEAL_ADMIN_REJECTED", event_key,
            actor_type="SYSTEM", actor_id=None,
            metadata={"appeal_id": appeal.id},
        )
        from app.services.arena_v3_settlement import refund_match
        return refund_match(db, match.id, reason="APPEAL_REJECTED")

    expected_winner = None
    if payload.owner_score > payload.opponent_score:
        expected_winner = match.owner_id
    elif payload.opponent_score > payload.owner_score:
        expected_winner = match.opponent_id
    if payload.winner_player_id != expected_winner:
        raise ArenaV3Conflict("Appeal winner does not match the submitted score")
    appeal.status = ArenaV3AppealStatus.ACCEPTED
    review.status = ArenaV3AIReviewStatus.COMPLETED
    review.detected_owner_score = payload.owner_score
    review.detected_opponent_score = payload.opponent_score
    review.winner_player_id = expected_winner
    review.provisional_winner_id = expected_winner
    review.score = f"{payload.owner_score}-{payload.opponent_score}"
    review.reason_code = "ADMIN_APPEAL_DECISION"
    review.reason = "Admin appeal decision"
    review.completed_at = datetime.now(timezone.utc)
    _event(
        repository, match, "APPEAL_ADMIN_APPROVED", event_key,
        actor_type="SYSTEM", actor_id=None,
        metadata={"appeal_id": appeal.id, "score": review.score},
    )
    from app.services.arena_v3_settlement import settle_completed_match
    return settle_completed_match(db, match.id)
