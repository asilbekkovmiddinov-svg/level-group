import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.models.match import ArenaNotificationDelivery, Match
from app.services.telegram_notifications import (
    TelegramNotificationPermanentError,
    send_admin_message,
)


logger = logging.getLogger(__name__)

ARENA_NOTIFICATION_MAX_ATTEMPTS = 3

EVENT_LABELS = {
    "CREATE": "Arena match yaratildi",
    "JOIN": "Arena matchga raqib qo‘shildi",
    "READY": "Arena ishtirokchisi tayyor",
    "PLAYING": "Arena match boshlandi",
    "EVIDENCE": "Arena natija dalili yuklandi",
    "RESOLVE": "Arena match yakunlandi",
    "CANCEL": "Arena match bekor qilindi",
}


def _recipients(match: Match) -> list[int]:
    return list(
        dict.fromkeys(
            value
            for value in (match.creator_telegram_id, match.opponent_telegram_id)
            if value is not None
        )
    )


def _message(match: Match, event_type: str) -> str:
    return (
        f"🎮 {EVENT_LABELS[event_type]}\n\n"
        f"Match: #{match.id}\n"
        f"Status: {match.status.value if hasattr(match.status, 'value') else match.status}\n"
        f"Stavka: {match.efc_amount} EFC"
    )


def _delivery_for_key(db, dedup_key: str):
    return (
        db.query(ArenaNotificationDelivery)
        .filter(ArenaNotificationDelivery.dedup_key == dedup_key)
        .first()
    )


def ensure_arena_delivery(
    db,
    match: Match,
    event_type: str,
    recipient_telegram_id: int,
    event_key: str,
) -> ArenaNotificationDelivery:
    dedup_key = f"arena:{match.id}:{event_type}:{event_key}:{recipient_telegram_id}"
    existing = _delivery_for_key(db, dedup_key)
    if existing:
        return existing

    delivery = ArenaNotificationDelivery(
        match_id=match.id,
        event_type=event_type,
        recipient_telegram_id=recipient_telegram_id,
        dedup_key=dedup_key,
        status="PENDING",
    )
    db.add(delivery)
    try:
        db.commit()
        db.refresh(delivery)
        return delivery
    except IntegrityError:
        db.rollback()
        existing = _delivery_for_key(db, dedup_key)
        if existing:
            return existing
        raise


def _attempt_delivery(db, delivery_id: int) -> bool:
    delivery = (
        db.query(ArenaNotificationDelivery)
        .filter(ArenaNotificationDelivery.id == delivery_id)
        .with_for_update()
        .first()
    )
    if not delivery:
        return False
    if delivery.status == "SENT":
        return True
    if delivery.attempts >= ARENA_NOTIFICATION_MAX_ATTEMPTS:
        return False

    delivery.status = "SENDING"
    delivery.attempts += 1
    delivery.last_attempt_at = datetime.now(timezone.utc)
    delivery.last_error = None
    attempt = delivery.attempts
    db.commit()

    match = db.query(Match).filter(Match.id == delivery.match_id).first()
    try:
        if not match:
            raise RuntimeError("Arena match not found for notification")
        result = send_admin_message(
            _message(match, delivery.event_type),
            chat_id=delivery.recipient_telegram_id,
        )
    except Exception as error:
        logger.exception(
            "arena_notification_failed match_id=%s event_type=%s recipient_telegram_id=%s "
            "attempt=%s max_attempts=%s exception_class=%s",
            delivery.match_id,
            delivery.event_type,
            delivery.recipient_telegram_id,
            attempt,
            ARENA_NOTIFICATION_MAX_ATTEMPTS,
            type(error).__name__,
        )
        current = (
            db.query(ArenaNotificationDelivery)
            .filter(ArenaNotificationDelivery.id == delivery_id)
            .with_for_update()
            .first()
        )
        if current and current.status == "SENDING" and current.attempts == attempt:
            current.status = "FAILED"
            current.last_error = type(error).__name__
            db.commit()
        else:
            db.rollback()
        return isinstance(error, TelegramNotificationPermanentError)

    current = (
        db.query(ArenaNotificationDelivery)
        .filter(ArenaNotificationDelivery.id == delivery_id)
        .with_for_update()
        .first()
    )
    if current and current.status == "SENDING" and current.attempts == attempt:
        current.status = "SENT"
        current.message_id = str(result.message_id)
        current.sent_at = datetime.now(timezone.utc)
        current.last_error = None
        db.commit()
        logger.info(
            "arena_notification_sent match_id=%s event_type=%s recipient_telegram_id=%s attempts=%s",
            current.match_id,
            current.event_type,
            current.recipient_telegram_id,
            current.attempts,
        )
        return True
    db.rollback()
    return False


def notify_arena_event(
    db,
    match: Match,
    event_type: str,
    actor_telegram_id: int | None = None,
) -> None:
    if event_type not in EVENT_LABELS:
        raise ValueError("Unsupported Arena notification event")
    event_key = str(actor_telegram_id) if actor_telegram_id is not None else "transition"
    for recipient in _recipients(match):
        delivery = ensure_arena_delivery(db, match, event_type, recipient, event_key)
        while delivery.status != "SENT" and delivery.attempts < ARENA_NOTIFICATION_MAX_ATTEMPTS:
            stop = _attempt_delivery(db, delivery.id)
            db.refresh(delivery)
            if stop:
                break

