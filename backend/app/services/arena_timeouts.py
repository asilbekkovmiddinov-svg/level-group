import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from app.crud import match as match_crud
from app.core.observability import increment
from app.models.match import Match, MatchResultType, MatchStatus
from app.services.arena_time import ensure_utc, utc_now


logger = logging.getLogger(__name__)

TIMEOUT_STATUSES = (
    MatchStatus.WAITING_PLAYER,
    MatchStatus.ROOM_READY,
    MatchStatus.PLAYING,
    MatchStatus.WAITING_ADMIN,
)
WORKER_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class ArenaTimeoutResult:
    match_id: int
    outcome: str
    previous_status: str | None = None
    current_status: str | None = None


@dataclass(frozen=True)
class ArenaTimeoutWorkerResult:
    scanned: int
    processed: int
    skipped: int
    failed: int
    retries: int


def _status_value(status) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _locked_match(db, match_id: int):
    return (
        db.query(Match)
        .filter(Match.id == match_id)
        .with_for_update(skip_locked=True)
        .first()
    )


def process_arena_timeout(
    db,
    match_id: int,
    now: datetime | None = None,
) -> ArenaTimeoutResult:
    now = ensure_utc(now) if now else utc_now()
    match = _locked_match(db, match_id)
    if not match:
        db.rollback()
        return ArenaTimeoutResult(match_id, "SKIPPED_LOCKED_OR_MISSING")

    previous_status = _status_value(match.status)
    if match.status not in TIMEOUT_STATUSES or not match.timeout_deadline_at:
        db.rollback()
        return ArenaTimeoutResult(match_id, "SKIPPED", previous_status, previous_status)
    if ensure_utc(match.timeout_deadline_at) > now:
        db.rollback()
        return ArenaTimeoutResult(match_id, "NOT_DUE", previous_status, previous_status)

    if match.status in {MatchStatus.WAITING_PLAYER, MatchStatus.ROOM_READY}:
        match_crud._unlock_efc(
            db=db,
            telegram_id=match.creator_telegram_id,
            amount=match.efc_amount,
            description="1vs1 Arena timeout, EFC unlock qilindi",
        )
        if match.opponent_telegram_id:
            match_crud._unlock_efc(
                db=db,
                telegram_id=match.opponent_telegram_id,
                amount=match.efc_amount,
                description="1vs1 Arena timeout, EFC unlock qilindi",
            )
        match.status = MatchStatus.CANCELLED
        match.result_type = MatchResultType.CANCELLED
        match.cancel_reason = f"{previous_status} timeout"
        match.resolved_at = now
    else:
        # In-game/admin timeouts require an admin decision; no reward or
        # balance mutation is performed by the worker.
        match.status = MatchStatus.TECHNICAL_REVIEW

    match.timeout_reason = f"{previous_status}_TIMEOUT"
    match.timeout_processed_at = now
    match.timeout_deadline_at = None
    match.updated_at = now
    db.commit()
    db.refresh(match)

    current_status = _status_value(match.status)
    increment("arena_timeout_processed_total")
    increment(f"arena_timeout_{previous_status.lower()}_total")
    logger.info(
        "arena_timeout_processed match_id=%s previous_status=%s current_status=%s",
        match.id,
        previous_status,
        current_status,
    )
    return ArenaTimeoutResult(match.id, "PROCESSED", previous_status, current_status)


def _due_match_ids(db, now: datetime, limit: int) -> list[int]:
    return [
        row[0]
        for row in (
            db.query(Match.id)
            .filter(Match.status.in_(TIMEOUT_STATUSES))
            .filter(Match.timeout_deadline_at.is_not(None))
            .filter(Match.timeout_deadline_at <= now)
            .order_by(Match.timeout_deadline_at.asc(), Match.id.asc())
            .limit(limit)
            .all()
        )
    ]


def run_arena_timeout_worker(
    db,
    limit: int = 50,
    now: datetime | None = None,
) -> ArenaTimeoutWorkerResult:
    now = ensure_utc(now) if now else utc_now()
    match_ids = _due_match_ids(db, now, limit)
    processed = skipped = failed = retries = 0

    for match_id in match_ids:
        for attempt in range(1, WORKER_MAX_ATTEMPTS + 1):
            try:
                result = process_arena_timeout(db, match_id, now)
                if result.outcome == "PROCESSED":
                    processed += 1
                else:
                    skipped += 1
                break
            except SQLAlchemyError:
                db.rollback()
                if attempt < WORKER_MAX_ATTEMPTS:
                    retries += 1
                    increment("arena_timeout_worker_retries_total")
                    logger.warning(
                        "arena_timeout_retry match_id=%s attempt=%s max_attempts=%s",
                        match_id,
                        attempt,
                        WORKER_MAX_ATTEMPTS,
                        exc_info=True,
                    )
                    continue
                failed += 1
                increment("arena_timeout_worker_failures_total")
                logger.exception(
                    "arena_timeout_failed match_id=%s attempts=%s",
                    match_id,
                    WORKER_MAX_ATTEMPTS,
                )

    increment("arena_timeout_worker_runs_total")
    logger.info(
        "arena_timeout_worker_completed scanned=%s processed=%s skipped=%s failed=%s retries=%s",
        len(match_ids),
        processed,
        skipped,
        failed,
        retries,
    )
    return ArenaTimeoutWorkerResult(len(match_ids), processed, skipped, failed, retries)

