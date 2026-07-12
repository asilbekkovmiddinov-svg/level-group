from dataclasses import dataclass
from datetime import datetime, timezone

from app.services.object_storage import StorageObjectNotFoundError, StorageOperationError
from app.services.telegram_notifications import (TelegramNotificationNetworkError, TelegramNotificationPermanentError, TelegramNotificationRateLimitError, TelegramNotificationTemporaryError, TelegramNotificationTimeoutError)
from app.core.config import RECEIPT_NOTIFICATION_MAX_ATTEMPTS, RECEIPT_NOTIFICATION_STALE_SECONDS
from app.models.deposit import Deposit
from app.models.user import User
from app.services.object_storage import download_object_bytes
from app.services.telegram_notifications import send_deposit_receipt_photo

class DepositNotificationNotFoundError(RuntimeError): pass
class DepositReceiptMissingError(RuntimeError): pass
class DepositNotificationAlreadySentError(RuntimeError): pass
class DepositNotificationInProgressError(RuntimeError): pass
class DepositNotificationAttemptsExceededError(RuntimeError): pass
class DepositNotificationStateError(RuntimeError): pass
class DepositNotificationDeliveryError(RuntimeError): pass

@dataclass(frozen=True)
class DepositReceiptNotificationResult:
    deposit_id: int; status: str; attempts: int; message_id: str | None; sent_at: datetime | None; retryable: bool
@dataclass(frozen=True)
class NotificationErrorClassification:
    retryable: bool; safe_message: str

def classify_notification_error(error: Exception) -> NotificationErrorClassification:
    if isinstance(error, (DepositReceiptMissingError, StorageObjectNotFoundError, TelegramNotificationPermanentError, DepositNotificationStateError)):
        return NotificationErrorClassification(False, "Notification cannot be delivered")
    if isinstance(error, (TelegramNotificationTimeoutError, TelegramNotificationNetworkError, TelegramNotificationRateLimitError, TelegramNotificationTemporaryError, StorageOperationError)):
        return NotificationErrorClassification(True, "Notification service temporarily unavailable")
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

def _locked_deposit(db, deposit_id: int):
    return db.query(Deposit).filter(Deposit.id == deposit_id).with_for_update().first()

def _caption(deposit, user) -> str:
    def clean(value): return " ".join(str(value or "—").split())
    username = f"@{clean(user.username)}" if user and user.username else "—"
    full_name = clean(user.first_name) if user else "—"
    return (f"💳 YANGI DEPOSIT RECEIPT\n\nID: #{deposit.id}\nTelegram ID: {deposit.telegram_id}\n"
            f"Username: {username}\nF.I.Sh: {full_name}\nSumma: {deposit.amount} UZS\n"
            f"Status: {clean(deposit.status)}\nYaratilgan: {clean(deposit.created_at)}\n"
            f"Receipt: {clean(deposit.receipt_uploaded_at)}")[:1024]

def _finalize_failed(db, deposit_id: int, attempt: int, error: Exception):
    classification = classify_notification_error(error)
    try:
        deposit = _locked_deposit(db, deposit_id)
        if not deposit or deposit.receipt_notification_status != "SENDING" or deposit.receipt_notification_attempts != attempt:
            raise DepositNotificationStateError("Notification state changed")
        deposit.receipt_notification_status = "FAILED"
        deposit.receipt_notification_last_error = classification.safe_message
        deposit.receipt_notification_message_id = None
        deposit.receipt_notification_sent_at = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    return DepositReceiptNotificationResult(deposit_id, "FAILED", attempt, None, None, classification.retryable)

def send_deposit_receipt_notification(db, deposit_id: int, now: datetime | None = None) -> DepositReceiptNotificationResult:
    now = now or datetime.now(timezone.utc)
    started = start_deposit_receipt_notification(db, deposit_id, now)
    try:
        deposit = db.query(Deposit).filter(Deposit.id == deposit_id).first()
        if not deposit or not deposit.receipt_object_key:
            raise DepositReceiptMissingError("Receipt missing")
        user = db.query(User).filter(User.telegram_id == deposit.telegram_id).first()
        receipt = download_object_bytes(deposit.receipt_object_key)
        extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[receipt.content_type]
        telegram = send_deposit_receipt_photo(receipt.content, receipt.content_type, f"receipt.{extension}", _caption(deposit, user))
    except (DepositReceiptMissingError, StorageOperationError, TelegramNotificationTimeoutError, TelegramNotificationNetworkError, TelegramNotificationRateLimitError, TelegramNotificationTemporaryError, TelegramNotificationPermanentError, TelegramNotificationResponseError) as error:
        return _finalize_failed(db, deposit_id, started.attempts, error)
    try:
        deposit = _locked_deposit(db, deposit_id)
        if not deposit or deposit.receipt_notification_status != "SENDING" or deposit.receipt_notification_attempts != started.attempts:
            raise DepositNotificationStateError("Notification state changed")
        deposit.receipt_notification_status = "SENT"
        deposit.receipt_notification_message_id = str(telegram.message_id)
        deposit.receipt_notification_sent_at = now
        deposit.receipt_notification_last_error = None
        db.commit()
        return DepositReceiptNotificationResult(deposit.id, "SENT", started.attempts, str(telegram.message_id), now, False)
    except Exception:
        db.rollback()
        raise
