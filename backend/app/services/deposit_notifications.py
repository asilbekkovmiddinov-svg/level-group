from dataclasses import dataclass
from datetime import datetime, timezone

from app.services.object_storage import StorageOperationError
from app.services.telegram_notifications import (TelegramNotificationNetworkError, TelegramNotificationPermanentError, TelegramNotificationRateLimitError, TelegramNotificationTemporaryError, TelegramNotificationTimeoutError)
from app.core.config import RECEIPT_NOTIFICATION_MAX_ATTEMPTS, RECEIPT_NOTIFICATION_STALE_SECONDS
from app.models.deposit import Deposit

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

def start_deposit_receipt_notification(db, deposit_id: int, now: datetime | None = None) -> DepositReceiptNotificationResult:
    now = now or datetime.now(timezone.utc)
    deposit = None
    previous = None
    try:
        deposit = db.query(Deposit).filter(Deposit.id == deposit_id).with_for_update().first()
        if not deposit: raise DepositNotificationNotFoundError("Deposit not found")
        if not deposit.receipt_object_key: raise DepositReceiptMissingError("Receipt missing")
        state = deposit.receipt_notification_status
        if state == "SENT": raise DepositNotificationAlreadySentError("Notification already sent")
        if state == "SENDING" and not is_notification_sending_stale(state, deposit.receipt_notification_last_attempt_at, now, RECEIPT_NOTIFICATION_STALE_SECONDS): raise DepositNotificationInProgressError("Notification in progress")
        if state not in {"PENDING", "FAILED", "SENDING"}: raise DepositNotificationStateError("Invalid notification state")
        if attempts_exceeded(deposit.receipt_notification_attempts, RECEIPT_NOTIFICATION_MAX_ATTEMPTS): raise DepositNotificationAttemptsExceededError("Notification attempts exceeded")
        previous = (deposit.receipt_notification_status, deposit.receipt_notification_attempts, deposit.receipt_notification_last_attempt_at, deposit.receipt_notification_last_error, deposit.receipt_notification_sent_at, deposit.receipt_notification_message_id)
        deposit.receipt_notification_status = "SENDING"; deposit.receipt_notification_attempts += 1; deposit.receipt_notification_last_attempt_at = now; deposit.receipt_notification_last_error = None; deposit.receipt_notification_sent_at = None; deposit.receipt_notification_message_id = None
        db.commit()
        return DepositReceiptNotificationResult(deposit.id, "SENDING", deposit.receipt_notification_attempts, None, None, True)
    except Exception:
        db.rollback()
        if deposit is not None and previous is not None:
            (deposit.receipt_notification_status, deposit.receipt_notification_attempts, deposit.receipt_notification_last_attempt_at, deposit.receipt_notification_last_error, deposit.receipt_notification_sent_at, deposit.receipt_notification_message_id) = previous
        raise
