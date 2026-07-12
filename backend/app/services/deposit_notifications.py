from dataclasses import dataclass
from datetime import datetime, timezone

from app.services.object_storage import StorageOperationError
from app.services.telegram_notifications import (TelegramNotificationNetworkError, TelegramNotificationPermanentError, TelegramNotificationRateLimitError, TelegramNotificationTemporaryError, TelegramNotificationTimeoutError)

class DepositNotificationNotFoundError(RuntimeError): pass
class DepositReceiptMissingError(RuntimeError): pass
class DepositNotificationAlreadySentError(RuntimeError): pass
class DepositNotificationInProgressError(RuntimeError): pass
class DepositNotificationAttemptsExceededError(RuntimeError): pass
class DepositNotificationStateError(RuntimeError): pass

@dataclass(frozen=True)
class DepositReceiptNotificationResult:
    deposit_id: int; status: str; attempts: int; message_id: str | None; sent_at: datetime | None; retryable: bool
@dataclass(frozen=True)
class NotificationErrorClassification:
    retryable: bool; safe_message: str

def classify_notification_error(error: Exception) -> NotificationErrorClassification:
    if isinstance(error, (TelegramNotificationTimeoutError, TelegramNotificationNetworkError, TelegramNotificationRateLimitError, TelegramNotificationTemporaryError, StorageOperationError)):
        return NotificationErrorClassification(True, "Notification service temporarily unavailable")
    if isinstance(error, (DepositReceiptMissingError, TelegramNotificationPermanentError, DepositNotificationStateError)):
        return NotificationErrorClassification(False, "Notification cannot be delivered")
    return NotificationErrorClassification(False, "Notification failed")

def is_notification_sending_stale(status: str, last_attempt_at: datetime | None, now: datetime | None, stale_seconds: int) -> bool:
    if status != "SENDING": return False
    if last_attempt_at is None: return True
    now = now or datetime.now(timezone.utc)
    if last_attempt_at.tzinfo is None: last_attempt_at = last_attempt_at.replace(tzinfo=timezone.utc)
    return (now - last_attempt_at).total_seconds() >= stale_seconds

def attempts_exceeded(attempts: int, max_attempts: int) -> bool:
    return attempts >= max_attempts
