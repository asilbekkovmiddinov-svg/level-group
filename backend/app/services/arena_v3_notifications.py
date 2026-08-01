from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.core import config
from app.models.arena_v3 import ArenaV3Match, ArenaV3NotificationDelivery
from app.services.telegram_notifications import (
    TelegramNotificationPermanentError,
    send_admin_message,
)


logger = logging.getLogger(__name__)

EVENT_LABELS = {
    "MATCH_FINISHED": "Arena V3 match yakunlandi",
    "MATCH_WON": "Arena V3 matchda g‘alaba",
    "MATCH_LOST": "Arena V3 match yakunlandi",
    "REFUND_COMPLETED": "Arena V3 refund yakunlandi",
    "APPEAL_REQUIRED": "Arena V3 appeal talab qilindi",
    "APPEAL_RESOLVED": "Arena V4 appeal yakunlandi",
    "MATCH_DRAW": "Arena V4 match durang bilan yakunlandi",
    "MATCH_CANCELLED": "Arena V4 match bekor qilindi",
    "REWARD_RELEASED": "Arena V4 mukofot foydalanish uchun ochildi",
}


def queue_v4_notification(
    repository, *, match_id: int, recipient_id: int, event_type: str,
    dedup_key: str,
):
    """Queue one durable notification inside the caller's transaction."""
    if repository.get_notification_by_dedup(dedup_key) is not None:
        return None
    return repository.add_notification(ArenaV3NotificationDelivery(
        match_id=match_id,
        recipient_id=recipient_id,
        event_type=event_type,
        dedup_key=dedup_key,
        status="PENDING",
    ))


def _utc_now():
    return datetime.now(timezone.utc)


def _message(match: ArenaV3Match, event_type: str) -> str:
    label = EVENT_LABELS.get(event_type, "Arena V3 yangilanishi")
    return (
        f"🎮 {label}\n\n"
        f"Match: {match.public_id}\n"
        f"Status: {match.status.value if hasattr(match.status, 'value') else match.status}\n"
        f"Stavka: {match.stake_efc} EFC"
    )


def _claim_next(db):
    now = _utc_now()
    stale = now - timedelta(
        seconds=config.ARENA_V3_NOTIFICATION_CLAIM_TTL_SECONDS
    )
    query = (
        select(ArenaV3NotificationDelivery)
        .where(
            ArenaV3NotificationDelivery.attempts
            < config.ARENA_V3_NOTIFICATION_MAX_ATTEMPTS,
            or_(
                ArenaV3NotificationDelivery.status.in_(("PENDING", "FAILED")),
                (
                    (ArenaV3NotificationDelivery.status == "SENDING")
                    & (ArenaV3NotificationDelivery.last_attempt_at < stale)
                ),
            ),
        )
        .order_by(
            ArenaV3NotificationDelivery.created_at,
            ArenaV3NotificationDelivery.id,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    delivery = db.execute(query).scalar_one_or_none()
    if delivery is None:
        db.rollback()
        return None
    delivery.status = "SENDING"
    delivery.attempts += 1
    delivery.last_attempt_at = now
    delivery.last_error = None
    delivery_id = delivery.id
    attempt = delivery.attempts
    db.commit()
    return delivery_id, attempt


def _finish(db, delivery_id: int, attempt: int, *, result=None, error=None):
    delivery = db.execute(
        select(ArenaV3NotificationDelivery)
        .where(ArenaV3NotificationDelivery.id == delivery_id)
        .with_for_update()
    ).scalar_one_or_none()
    if (
        delivery is None
        or delivery.status != "SENDING"
        or delivery.attempts != attempt
    ):
        db.rollback()
        return False
    if error is None:
        delivery.status = "SUCCESS"
        delivery.message_id = str(result.message_id)
        delivery.sent_at = _utc_now()
        delivery.last_error = None
    else:
        delivery.status = "FAILED"
        delivery.last_error = type(error).__name__
        if isinstance(error, TelegramNotificationPermanentError):
            delivery.attempts = config.ARENA_V3_NOTIFICATION_MAX_ATTEMPTS
    db.commit()
    return error is None


def process_next_notification(db) -> bool | None:
    claimed = _claim_next(db)
    if claimed is None:
        return None
    delivery_id, attempt = claimed
    delivery = db.get(ArenaV3NotificationDelivery, delivery_id)
    match = db.get(ArenaV3Match, delivery.match_id) if delivery else None
    try:
        if delivery is None or match is None:
            raise RuntimeError("Arena V3 notification source is missing")
        result = send_admin_message(
            _message(match, delivery.event_type),
            chat_id=delivery.recipient_id,
        )
    except Exception as error:
        logger.exception(
            "arena_v3_notification_failed delivery_id=%s attempt=%s",
            delivery_id, attempt,
        )
        _finish(db, delivery_id, attempt, error=error)
        return False
    _finish(db, delivery_id, attempt, result=result)
    logger.info(
        "arena_v3_notification_success delivery_id=%s attempt=%s",
        delivery_id, attempt,
    )
    return True


def run_notification_queue(db, *, limit: int = 50) -> int:
    processed = 0
    for _ in range(limit):
        result = process_next_notification(db)
        if result is None:
            break
        processed += 1
    return processed


class ArenaV3NotificationWorker:
    def __init__(self, session_factory, interval_seconds=None):
        self.session_factory = session_factory
        self.interval_seconds = (
            interval_seconds or config.ARENA_V3_NOTIFICATION_INTERVAL_SECONDS
        )
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="arena-v3-notification-worker", daemon=True
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
                run_notification_queue(db)
            except Exception:
                db.rollback()
                logger.exception("arena_v3_notification_worker_tick_failed")
            finally:
                db.close()
            self._stop.wait(self.interval_seconds)
