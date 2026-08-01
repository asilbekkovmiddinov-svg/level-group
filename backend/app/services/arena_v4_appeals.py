from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.models.arena_v3 import (
    ArenaV3Appeal,
    ArenaV3AppealStatus,
    ArenaV3MatchEvent,
    ArenaV3Status,
    ArenaV4AdminReview,
    ArenaV4AdminReviewStatus,
    ArenaV4ReviewType,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3 import (
    ArenaV3Conflict,
    ArenaV3Forbidden,
    ArenaV3NotFound,
)


def _utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def ensure_v4_appeal_upload_allowed(
    db, *, match_id: int, player_id: int, idempotency_key: str, now=None
):
    repository = ArenaV3Repository(db)
    match = repository.get_match(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V4 match not found")
    previous = repository.get_event_by_idempotency(
        match.id, f"v4-appeal:{idempotency_key}"
    )
    appeal = repository.get_appeal_for_update(match.id)
    if previous is not None:
        if previous.actor_id != player_id or appeal is None:
            raise ArenaV3Conflict("Idempotency key belongs to another appeal")
        return appeal
    if player_id not in {match.owner_id, match.opponent_id}:
        raise ArenaV3Forbidden("Player is not a match participant")
    if match.status != ArenaV3Status.FINISHED:
        raise ArenaV3Conflict("Appeal is only available for finished matches")
    now = now or datetime.now(timezone.utc)
    if (
        match.appeal_deadline_at is None
        or _utc(match.appeal_deadline_at) <= now
    ):
        raise ArenaV3Conflict("Arena V4 appeal deadline has passed")
    if appeal is not None or match.has_appeal:
        raise ArenaV3Conflict("Arena V4 appeal already exists")
    return None


def submit_v4_video_appeal(
    db,
    *,
    match_id: int,
    player_id: int,
    payload,
    idempotency_key: str,
    storage_key: str,
    file_hash: str,
    telegram_file_id: str | None = None,
    now=None,
):
    repository = ArenaV3Repository(db)
    match = repository.get_match_for_update(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V4 match not found")
    event_key = f"v4-appeal:{idempotency_key}"
    previous = repository.get_event_by_idempotency(match.id, event_key)
    appeal = repository.get_appeal_for_update(match.id)
    if previous is not None:
        if previous.actor_id != player_id or appeal is None:
            raise ArenaV3Conflict("Idempotency key belongs to another appeal")
        return appeal
    if player_id not in {match.owner_id, match.opponent_id}:
        raise ArenaV3Forbidden("Player is not a match participant")
    if match.status != ArenaV3Status.FINISHED:
        raise ArenaV3Conflict("Appeal is only available for finished matches")
    now = now or datetime.now(timezone.utc)
    if (
        match.appeal_deadline_at is None
        or _utc(match.appeal_deadline_at) <= now
    ):
        raise ArenaV3Conflict("Arena V4 appeal deadline has passed")
    if appeal is not None or match.has_appeal:
        raise ArenaV3Conflict("Arena V4 appeal already exists")

    appeal = repository.add_appeal(ArenaV3Appeal(
        match_id=match.id,
        submitted_by=player_id,
        reason_code="PLAYER_APPEAL",
        reason=payload.reason,
        video_storage_key=storage_key,
        telegram_file_id=telegram_file_id,
        file_hash=file_hash,
        status=ArenaV3AppealStatus.PENDING,
        submitted_at=now,
        deadline_at=match.appeal_deadline_at,
    ))
    review = repository.add_admin_review(ArenaV4AdminReview(
        match_id=match.id,
        review_type=ArenaV4ReviewType.APPEAL,
        status=ArenaV4AdminReviewStatus.PENDING,
        result_version=match.result_version,
        expected_match_version=match.version,
    ))
    match.has_appeal = True
    repository.add_event(ArenaV3MatchEvent(
        match_id=match.id,
        event_type="V4_APPEAL_SUBMITTED",
        from_status=ArenaV3Status.FINISHED.value,
        to_status=ArenaV3Status.FINISHED.value,
        actor_type="USER",
        actor_id=player_id,
        idempotency_key=event_key,
        event_metadata={"appeal_id": appeal.id, "review_id": review.id},
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ArenaV3Conflict("Arena V4 appeal already exists") from exc
    db.refresh(appeal)
    return appeal
