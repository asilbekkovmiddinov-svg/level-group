import logging
import threading
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import PENALTY_DUEL_TIMEOUT_INTERVAL_SECONDS
from app.models.penalty_duel import PenaltyDuelMatch, PenaltyDuelStatus
from app.services.penalty_duel import process_timeout, utc_now


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PenaltyDuelTimeoutResult:
    scanned: int
    processed: int
    skipped: int
    failed: int


def due_match_ids(db, now: datetime, limit: int = 100) -> list[str]:
    return [
        row[0]
        for row in (
            db.query(PenaltyDuelMatch.id)
            .filter(PenaltyDuelMatch.status == PenaltyDuelStatus.ACTIVE)
            .filter(PenaltyDuelMatch.round_deadline_at.is_not(None))
            .filter(PenaltyDuelMatch.round_deadline_at <= now)
            .order_by(PenaltyDuelMatch.round_deadline_at.asc(), PenaltyDuelMatch.id.asc())
            .limit(limit)
            .all()
        )
    ]


def run_penalty_duel_timeout_worker(
    db,
    limit: int = 100,
    now: datetime | None = None,
) -> PenaltyDuelTimeoutResult:
    now = now or utc_now()
    match_ids = due_match_ids(db, now, limit)
    processed = skipped = failed = 0
    for match_id in match_ids:
        try:
            match = db.query(PenaltyDuelMatch).filter_by(id=match_id).first()
            if match is None or match.status != PenaltyDuelStatus.ACTIVE:
                db.rollback()
                skipped += 1
                continue
            previous_status = match.status
            result = process_timeout(db, match.id, match.player_one_id, now=now)
            if previous_status == PenaltyDuelStatus.ACTIVE and result.status != previous_status:
                processed += 1
            else:
                skipped += 1
        except SQLAlchemyError:
            db.rollback()
            failed += 1
            logger.exception("penalty_duel_timeout_failed match_id=%s", match_id)
        except Exception:
            db.rollback()
            failed += 1
            logger.exception("penalty_duel_timeout_unexpected match_id=%s", match_id)
    logger.info(
        "penalty_duel_timeout_worker_completed scanned=%s processed=%s skipped=%s failed=%s",
        len(match_ids),
        processed,
        skipped,
        failed,
    )
    return PenaltyDuelTimeoutResult(len(match_ids), processed, skipped, failed)


class PenaltyDuelTimeoutWorker:
    def __init__(
        self,
        session_factory,
        interval_seconds: float = PENALTY_DUEL_TIMEOUT_INTERVAL_SECONDS,
    ):
        self.session_factory = session_factory
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="penalty-duel-timeouts",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.interval_seconds + 1, 5))

    def _run(self) -> None:
        while not self._stop.is_set():
            db = self.session_factory()
            try:
                run_penalty_duel_timeout_worker(db)
            except Exception:
                db.rollback()
                logger.exception("penalty_duel_timeout_tick_failed")
            finally:
                db.close()
            self._stop.wait(self.interval_seconds)
