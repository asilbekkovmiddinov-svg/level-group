import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.core import config
from app.core.config import ARENA_TIMEOUT_INTERVAL_SECONDS
from app.models.arena_v3 import (
    ArenaV3AIReview,
    ArenaV3AIReviewStatus,
    ArenaV3Match,
    ArenaV3MatchEvent,
    ArenaV3EvidenceStatus,
    ArenaV3Status,
    ArenaV4AdminReview,
    ArenaV4AdminReviewStatus,
    ArenaV4ReviewType,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3 import ArenaV3Conflict, ArenaV3NotFound
from app.services.arena_v3_state_machine import transition_arena_v3
from app.services.arena_v3_ai import (
    ArenaV3AnalysisError, OpenAIVisionOCR, normalize_ocr_result, winner_for_scores,
)
from app.services.object_storage import download_object_bytes


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
    if review.status in {
        ArenaV3AIReviewStatus.COMPLETED,
        ArenaV3AIReviewStatus.APPEAL_REQUIRED,
    }:
        raise ArenaV3Conflict("Arena V3 AI review is already finalized")
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
    if match.status not in {
        ArenaV3Status.PLAYING,
        ArenaV3Status.WAITING_SCREENSHOT,
    } or not match.screenshot_deadline_at:
        db.rollback()
        return ArenaV3TimeoutResult(match_id, "SKIPPED", status=match.status.value)
    if match.status == ArenaV3Status.PLAYING:
        if (
            not match.screenshot_started_at
            or _utc(match.screenshot_started_at) > now
        ):
            db.rollback()
            return ArenaV3TimeoutResult(
                match_id, "NOT_DUE", status=match.status.value
            )
        previous = ArenaV3Status(match.status)
        transition_arena_v3(match, ArenaV3Status.WAITING_SCREENSHOT)
        _system_event(
            repository,
            match,
            event_type="SCREENSHOT_WINDOW_STARTED",
            idempotency_key="screenshot-window-started",
            from_status=previous,
        )
        db.commit()
        db.refresh(match)
        return ArenaV3TimeoutResult(
            match.id, "WINDOW_OPENED", status=match.status.value
        )
    if _utc(match.screenshot_deadline_at) > now:
        db.rollback()
        return ArenaV3TimeoutResult(match_id, "NOT_DUE", status=match.status.value)

    screenshots = list(repository.list_screenshots(match.id))
    previous = ArenaV3Status(match.status)
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
        transition_arena_v3(match, ArenaV3Status.WAITING_ADMIN)
        if repository.get_initial_admin_review(match.id, match.result_version) is None:
            repository.add_admin_review(ArenaV4AdminReview(
                match_id=match.id, review_type=ArenaV4ReviewType.INITIAL,
                status=ArenaV4AdminReviewStatus.PENDING,
                result_version=match.result_version,
                expected_match_version=match.version,
            ))
    else:
        transition_arena_v3(match, ArenaV3Status.CANCELLED)
        match.cancel_reason = "NO_SCREENSHOTS_TIMEOUT"
        if config.ARENA_V3_SETTLEMENT_ENABLED:
            from app.services.arena_v3_settlement import refund_match
            refund_match(
                db, match.id, reason="NO_SCREENSHOTS_TIMEOUT"
            )
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
            .filter(ArenaV3Match.status.in_([
                ArenaV3Status.PLAYING,
                ArenaV3Status.WAITING_SCREENSHOT,
            ]))
            .filter(ArenaV3Match.screenshot_deadline_at.is_not(None))
            .filter(
                (
                    (ArenaV3Match.status == ArenaV3Status.PLAYING)
                    & (ArenaV3Match.screenshot_started_at <= now)
                )
                | (
                    (ArenaV3Match.status == ArenaV3Status.WAITING_SCREENSHOT)
                    & (ArenaV3Match.screenshot_deadline_at <= now)
                )
            )
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
    def __init__(self, session_factory, interval_seconds=None, analyzer_factory=OpenAIVisionOCR):
        self.session_factory = session_factory
        self.interval_seconds = interval_seconds or config.ARENA_V3_AI_INTERVAL_SECONDS
        self.analyzer_factory = analyzer_factory
        self._stop = threading.Event()
        self._thread = None

    def claim(self, match_id: int) -> ArenaV3AIReview:
        db = self.session_factory()
        try:
            return start_ai_review(db, match_id)
        finally:
            db.close()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="arena-v3-ai", daemon=True
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
                processed = process_next_ai_review(db, analyzer=self.analyzer_factory())
                if processed is None:
                    from app.services.arena_v3_settlement import run_ai_outcome_queue
                    processed = run_ai_outcome_queue(db)
            except Exception:
                db.rollback()
                processed = None
                logger.exception("arena_v3_ai_worker_tick_failed")
            finally:
                db.close()
            self._stop.wait(0 if processed else self.interval_seconds)


def _claim_next_ai_review(db):
    repository = ArenaV3Repository(db)
    review = repository.claim_pending_ai_review()
    if review is None:
        db.rollback()
        return None
    match = repository.get_match_for_update(review.match_id)
    if match is None or match.status != ArenaV3Status.AI_REVIEW:
        review.status = ArenaV3AIReviewStatus.FAILED
        review.reason_code = "MATCH_NOT_READY"
        review.reason = "Arena match is not ready for AI review"
        review.completed_at = datetime.now(timezone.utc)
        db.commit()
        return None
    review.status = ArenaV3AIReviewStatus.RUNNING
    review.attempt_count += 1
    review.started_at = datetime.now(timezone.utc)
    review.completed_at = None
    _system_event(
        repository, match, event_type="AI_STARTED",
        idempotency_key=f"ai-started:{review.id}:{review.attempt_count}",
        from_status=ArenaV3Status.AI_REVIEW,
        metadata={"review_id": review.id, "attempt": review.attempt_count},
    )
    db.commit()
    return review.id


def _finish_failed(db, review_id: int, error: ArenaV3AnalysisError):
    repository = ArenaV3Repository(db)
    review = repository.get_ai_review_for_update(review_id)
    match = repository.get_match_for_update(review.match_id)
    review.status = ArenaV3AIReviewStatus.FAILED
    review.reason_code = error.code
    review.reason = str(error)
    review.completed_at = datetime.now(timezone.utc)
    _system_event(
        repository, match, event_type="AI_FAILED",
        idempotency_key=f"ai-failed:{review.id}:{review.attempt_count}",
        from_status=ArenaV3Status.AI_REVIEW,
        metadata={"review_id": review.id, "reason_code": error.code},
    )
    db.commit()
    db.refresh(review)
    if config.ARENA_V3_REFUND_ON_AI_FAILURE:
        from app.services.arena_v3_settlement import handle_ai_outcome
        handle_ai_outcome(db, review.match_id)
    return review


def process_next_ai_review(db, *, analyzer=None):
    review_id = _claim_next_ai_review(db)
    if review_id is None:
        return None
    return process_ai_review(db, review_id, analyzer=analyzer)


def process_ai_review(db, review_id: int, *, analyzer=None):
    analyzer = analyzer or OpenAIVisionOCR()
    repository = ArenaV3Repository(db)
    review = repository.get_ai_review_for_update(review_id)
    if review is None:
        raise ArenaV3NotFound("Arena V3 AI review not found")
    if review.status != ArenaV3AIReviewStatus.RUNNING:
        raise ArenaV3Conflict("Arena V3 AI review is not running")
    match = repository.get_match(review.match_id)
    screenshots = list(repository.list_screenshots(match.id))
    if not screenshots:
        return _finish_failed(
            db, review.id, ArenaV3AnalysisError("SCREENSHOT_MISSING", "No screenshot is available")
        )

    normalized = []
    raw_results = []
    response_ids = []
    try:
        for screenshot in screenshots:
            downloaded = download_object_bytes(screenshot.storage_key)
            ocr, response_id = analyzer.analyze(downloaded.content, downloaded.content_type)
            result = normalize_ocr_result(
                ocr,
                owner_username=match.owner_efootball_username,
                opponent_username=match.opponent_efootball_username,
            )
            screenshot.validation_status = ArenaV3EvidenceStatus.VALID
            screenshot.validation_reason = None
            screenshot.identity_status = "MATCHED"
            screenshot.extracted_owner_score = result.owner_score
            screenshot.extracted_opponent_score = result.opponent_score
            screenshot.extraction_confidence = result.confidence
            normalized.append(result)
            raw_results.append({"screenshot_id": screenshot.id, **result.raw})
            response_ids.append(response_id)
    except ArenaV3AnalysisError as error:
        if "screenshot" in locals():
            screenshot.validation_status = ArenaV3EvidenceStatus.INVALID
            screenshot.validation_reason = str(error)
            if error.code == "USERNAME_MISMATCH":
                screenshot.identity_status = "MISMATCH"
        return _finish_failed(db, review.id, error)
    except Exception as error:
        logger.exception("arena_v3_ai_processing_failed review_id=%s", review.id)
        return _finish_failed(
            db, review.id, ArenaV3AnalysisError("AI_PROCESSING_FAILED", "AI review processing failed")
        )

    _system_event(
        repository, match, event_type="OCR_COMPLETED",
        idempotency_key=f"ocr-completed:{review.id}:{review.attempt_count}",
        from_status=ArenaV3Status.AI_REVIEW,
        metadata={"review_id": review.id, "screenshot_count": len(normalized)},
    )
    scores = {(item.owner_score, item.opponent_score) for item in normalized}
    review.raw_result = {"screenshots": raw_results, "provider_response_ids": response_ids}
    review.model_name = config.ARENA_V3_AI_MODEL
    review.completed_at = datetime.now(timezone.utc)
    review.confidence = min(item.confidence for item in normalized)
    if len(scores) > 1:
        review.status = ArenaV3AIReviewStatus.APPEAL_REQUIRED
        review.reason_code = "SCREENSHOT_CONFLICT"
        review.reason = "Submitted screenshots contain different scores"
        review.conflict_type = "SCORE_MISMATCH"
        _system_event(
            repository, match, event_type="AI_CONFLICT",
            idempotency_key=f"ai-conflict:{review.id}:{review.attempt_count}",
            from_status=ArenaV3Status.AI_REVIEW,
            metadata={"review_id": review.id},
        )
    else:
        owner_score, opponent_score = next(iter(scores))
        winner_id, reason = winner_for_scores(match, owner_score, opponent_score)
        review.status = ArenaV3AIReviewStatus.COMPLETED
        review.detected_owner_score = owner_score
        review.detected_opponent_score = opponent_score
        review.provisional_winner_id = winner_id
        review.winner_player_id = winner_id
        review.score = f"{owner_score}-{opponent_score}"
        review.reason_code = reason
        review.reason = reason.replace("_", " ").title()
        _system_event(
            repository, match, event_type="WINNER_DETECTED",
            idempotency_key=f"winner-detected:{review.id}:{review.attempt_count}",
            from_status=ArenaV3Status.AI_REVIEW,
            metadata={"review_id": review.id, "winner_player_id": winner_id, "score": review.score},
        )
        _system_event(
            repository, match, event_type="AI_COMPLETED",
            idempotency_key=f"ai-completed:{review.id}:{review.attempt_count}",
            from_status=ArenaV3Status.AI_REVIEW,
            metadata={"review_id": review.id, "score": review.score},
        )
    db.commit()
    db.refresh(review)
    if (
        review.status == ArenaV3AIReviewStatus.APPEAL_REQUIRED
        or config.ARENA_V3_SETTLEMENT_ENABLED
    ):
        from app.services.arena_v3_settlement import handle_ai_outcome
        handle_ai_outcome(db, review.match_id)
    return review
