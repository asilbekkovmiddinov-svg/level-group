import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import ARENA_TIMEOUT_INTERVAL_SECONDS
from app.models.arena_v3 import (
    ArenaV3AIReview,
    ArenaV3AIReviewStatus,
    ArenaV3Match,
    ArenaV3MatchEvent,
    ArenaV3Status,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3 import ArenaV3Conflict, ArenaV3NotFound
from app.services.arena_v3_state_machine import transition_arena_v3


logger = logging.getLogger(__name__)
AI_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class ArenaV3TimeoutResult:
    match_id: int
    outcome: str
    screenshot_count: int = 0
    status: str | None = None


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _system_event(
    repository: ArenaV3Repository,
    match: ArenaV3Match,
    *,
    event_type: str,
    idempotency_key: str,
    from_status: ArenaV3Status,
    metadata: dict | None = None,
) -> None:
    repository.add_event(ArenaV3MatchEvent(
        match_id=match.id,
        event_type=event_type,
        from_status=from_status.value,
        to_status=ArenaV3Status(match.status).value,
        actor_type="SYSTEM",
        actor_id=None,
        idempotency_key=idempotency_key,
        event_metadata=metadata,
    ))


def enqueue_ai_review(
    db, match: ArenaV3Match, screenshots=None
) -> ArenaV3AIReview:
    repository = ArenaV3Repository(db)
    existing = repository.get_latest_ai_review(match.id)
    if existing:
        return existing
    screenshots = list(screenshots or repository.list_screenshots(match.id))
    by_player = {item.player_id: item for item in screenshots}
    return repository.add_ai_review(ArenaV3AIReview(
        match_id=match.id,
        status=ArenaV3AIReviewStatus.PENDING,
        owner_screenshot_id=getattr(by_player.get(match.owner_id), "id", None),
        opponent_screenshot_id=getattr(by_player.get(match.opponent_id), "id", None),
        attempt_count=0,
    ))


def retry_ai_review(db, review_id: int) -> ArenaV3AIReview:
    repository = ArenaV3Repository(db)
    review = repository.get_ai_review_for_update(review_id)
    if review is None:
        raise ArenaV3NotFound("Arena V3 AI review not found")
    if review.status != ArenaV3AIReviewStatus.FAILED:
        raise ArenaV3Conflict("Only failed AI review can be retried")
    if review.attempt_count >= AI_MAX_ATTEMPTS:
        raise ArenaV3Conflict("Arena V3 AI retry limit reached")
    review.status = ArenaV3AIReviewStatus.PENDING
    review.started_at = None
    review.completed_at = None
    db.commit()
    db.refresh(review)
    return review


def start_ai_review(db, match_id: int) -> ArenaV3AIReview:
    repository = ArenaV3Repository(db)
    match = repository.get_match_for_update(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V3 match not found")
    if match.status != ArenaV3Status.AI_REVIEW:
        raise ArenaV3Conflict("Arena V3 match is not ready for AI review")
    review = enqueue_ai_review(db, match)
    if review.status == ArenaV3AIReviewStatus.RUNNING:
        return review
    if review.status == ArenaV3AIReviewStatus.COMPLETED:
        raise ArenaV3Conflict("Arena V3 AI review is already completed")
    if review.status == ArenaV3AIReviewStatus.FAILED:
        if review.attempt_count >= AI_MAX_ATTEMPTS:
            raise ArenaV3Conflict("Arena V3 AI retry limit reached")
        review.status = ArenaV3AIReviewStatus.PENDING

    review.status = ArenaV3AIReviewStatus.RUNNING
    review.attempt_count += 1
    review.started_at = datetime.now(timezone.utc)
    review.completed_at = None
    _system_event(
        repository,
        match,
        event_type="AI_STARTED",
        idempotency_key=f"ai-started:{review.id}:{review.attempt_count}",
        from_status=ArenaV3Status.AI_REVIEW,
        metadata={"review_id": review.id, "attempt": review.attempt_count},
    )
    db.commit()
    db.refresh(review)
    return review


def complete_ai_review(
    db, review_id: int, *, succeeded: bool
) -> ArenaV3AIReview:
    repository = ArenaV3Repository(db)
    review = repository.get_ai_review_for_update(review_id)
    if review is None:
        raise ArenaV3NotFound("Arena V3 AI review not found")
    if review.status != ArenaV3AIReviewStatus.RUNNING:
        raise ArenaV3Conflict("Arena V3 AI review is not running")
    match = repository.get_match_for_update(review.match_id)
    review.status = (
        ArenaV3AIReviewStatus.COMPLETED
        if succeeded else ArenaV3AIReviewStatus.FAILED
    )
    review.completed_at = datetime.now(timezone.utc)
    _system_event(
        repository,
        match,
        event_type="AI_COMPLETED",
        idempotency_key=f"ai-completed:{review.id}:{review.attempt_count}",
        from_status=ArenaV3Status.AI_REVIEW,
        metadata={"review_id": review.id, "succeeded": succeeded},
    )
    db.commit()
    db.refresh(review)
    return review


def process_screenshot_timeout(
    db, match_id: int, *, now: datetime | None = None
) -> ArenaV3TimeoutResult:
    now = now or datetime.now(timezone.utc)
    repository = ArenaV3Repository(db)
    match = repository.get_match_for_update(match_id)
    if match is None:
        db.rollback()
        return ArenaV3TimeoutResult(match_id, "MISSING")
    if match.status != ArenaV3Status.PLAYING or not match.screenshot_deadline_at:
        db.rollback()
        return ArenaV3TimeoutResult(match_id, "SKIPPED", status=match.status.value)
    if _utc(match.screenshot_deadline_at) > now:
        db.rollback()
        return ArenaV3TimeoutResult(match_id, "NOT_DUE", status=match.status.value)

    screenshots = list(repository.list_screenshots(match.id))
    previous = ArenaV3Status(match.status)
    transition_arena_v3(match, ArenaV3Status.WAITING_SCREENSHOT)
    _system_event(
        repository,
        match,
        event_type="SCREENSHOT_TIMEOUT",
        idempotency_key="screenshot-timeout",
        from_status=previous,
        metadata={"screenshot_count": len(screenshots)},
    )
    match.screenshot_deadline_at = None
    if screenshots:
        transition_arena_v3(match, ArenaV3Status.AI_REVIEW)
        match.ai_review_started_at = now
        enqueue_ai_review(db, match, screenshots)
    else:
        transition_arena_v3(match, ArenaV3Status.CANCELLED)
        match.cancel_reason = "NO_SCREENSHOTS_TIMEOUT"
    db.commit()
    db.refresh(match)
    return ArenaV3TimeoutResult(
        match.id, "PROCESSED", len(screenshots), ArenaV3Status(match.status).value
    )


def run_screenshot_timeout_queue(db, *, limit: int = 50, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    match_ids = [
        row[0] for row in (
            db.query(ArenaV3Match.id)
            .filter(ArenaV3Match.status == ArenaV3Status.PLAYING)
            .filter(ArenaV3Match.screenshot_deadline_at.is_not(None))
            .filter(ArenaV3Match.screenshot_deadline_at <= now)
            .order_by(ArenaV3Match.screenshot_deadline_at, ArenaV3Match.id)
            .limit(limit)
            .all()
        )
    ]
    results = []
    for match_id in match_ids:
        try:
            results.append(process_screenshot_timeout(db, match_id, now=now))
        except SQLAlchemyError:
            db.rollback()
            logger.exception("arena_v3_screenshot_timeout_failed match_id=%s", match_id)
    return results


class ArenaV3ScreenshotTimeoutWorker:
    def __init__(self, session_factory, interval_seconds=ARENA_TIMEOUT_INTERVAL_SECONDS):
        self.session_factory = session_factory
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="arena-v3-screenshot-timeouts", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.interval_seconds + 1, 5))

    def _run(self):
        while not self._stop.is_set():
            db = self.session_factory()
            try:
                run_screenshot_timeout_queue(db)
            except Exception:
                db.rollback()
                logger.exception("arena_v3_screenshot_timeout_tick_failed")
            finally:
                db.close()
            self._stop.wait(self.interval_seconds)


class ArenaV3AIWorker:
    """Queue consumer boundary. Real AI processing is implemented in Sprint 6."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def claim(self, match_id: int) -> ArenaV3AIReview:
        db = self.session_factory()
        try:
            return start_ai_review(db, match_id)
        finally:
            db.close()
