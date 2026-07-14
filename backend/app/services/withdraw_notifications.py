from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import WITHDRAW_NOTIFICATION_MAX_ATTEMPTS, WITHDRAW_NOTIFICATION_STALE_SECONDS
from app.models.user import User
from app.models.withdraw import Withdraw
from app.services.deposit_notifications import classify_notification_error, is_notification_sending_stale
from app.services.telegram_notifications import (
    TelegramNotificationConfigError,
    TelegramNotificationNetworkError,
    TelegramNotificationPermanentError,
    TelegramNotificationRateLimitError,
    TelegramNotificationResponseError,
    TelegramNotificationTemporaryError,
    TelegramNotificationTimeoutError,
    send_admin_message,
)


class WithdrawNotificationNotFoundError(RuntimeError): pass
class WithdrawNotificationAlreadySentError(RuntimeError): pass
class WithdrawNotificationInProgressError(RuntimeError): pass
class WithdrawNotificationAttemptsExceededError(RuntimeError): pass
class WithdrawNotificationStateError(RuntimeError): pass


@dataclass(frozen=True)
class WithdrawNotificationResult:
    withdraw_id: int
    status: str
    attempts: int
    message_id: str | None
    sent_at: datetime | None
    retryable: bool


def _locked_withdraw(db, withdraw_id: int):
    return db.query(Withdraw).filter(Withdraw.id == withdraw_id).with_for_update().first()


def start_withdraw_notification(db, withdraw_id: int, now: datetime | None = None) -> WithdrawNotificationResult:
    now = now or datetime.now(timezone.utc)
    withdraw = None
    previous = None
    try:
        withdraw = _locked_withdraw(db, withdraw_id)
        if not withdraw:
            raise WithdrawNotificationNotFoundError("Withdraw not found")
        state = withdraw.notification_status
        if state == "SENT":
            raise WithdrawNotificationAlreadySentError("Notification already sent")
        if state == "SENDING" and not is_notification_sending_stale(
            state, withdraw.notification_last_attempt_at, now, WITHDRAW_NOTIFICATION_STALE_SECONDS
        ):
            raise WithdrawNotificationInProgressError("Notification in progress")
        if state not in {"PENDING", "FAILED", "SENDING"}:
            raise WithdrawNotificationStateError("Invalid notification state")
        if withdraw.notification_attempts >= WITHDRAW_NOTIFICATION_MAX_ATTEMPTS:
            raise WithdrawNotificationAttemptsExceededError("Notification attempts exceeded")
        previous = (
            withdraw.notification_status, withdraw.notification_attempts,
            withdraw.notification_last_attempt_at, withdraw.notification_last_error,
            withdraw.notification_sent_at, withdraw.notification_message_id,
        )
        withdraw.notification_status = "SENDING"
        withdraw.notification_attempts += 1
        withdraw.notification_last_attempt_at = now
        withdraw.notification_last_error = None
        withdraw.notification_sent_at = None
        withdraw.notification_message_id = None
        db.commit()
        return WithdrawNotificationResult(withdraw.id, "SENDING", withdraw.notification_attempts, None, None, True)
    except Exception:
        db.rollback()
        if withdraw is not None and previous is not None:
            (
                withdraw.notification_status, withdraw.notification_attempts,
                withdraw.notification_last_attempt_at, withdraw.notification_last_error,
                withdraw.notification_sent_at, withdraw.notification_message_id,
            ) = previous
        raise


def _message(withdraw, user) -> str:
    def clean(value): return " ".join(str(value or "—").split())
    username = f"@{clean(user.username)}" if user and user.username else clean(user.first_name if user else None)
    return (
        "💸 YANGI WITHDRAW\n\n"
        f"🆔 Buyurtma: #{withdraw.id}\n\n"
        f"👤 Mijoz: {username}\n"
        f"🆔 Telegram ID: {withdraw.telegram_id}\n\n"
        "🎮 Xizmat: UZS yechish\n"
        f"💵 Summa: {withdraw.amount:,.0f} so‘m\n"
        f"🏦 Bank: {clean(withdraw.bank_name)}\n"
        f"💳 Karta: {clean(withdraw.card_number)}\n"
        f"👤 Karta egasi: {clean(withdraw.card_holder)}\n\n"
        "⏳ Muddat: 24 soatgacha\n"
        "📌 Status: PENDING\n\n"
        "👇 Adminlardan biri qabul qilsin."
    )


def _finalize_failed(db, withdraw_id: int, attempt: int, error: Exception) -> WithdrawNotificationResult:
    classification = classify_notification_error(error)
    try:
        withdraw = _locked_withdraw(db, withdraw_id)
        if not withdraw or withdraw.notification_status != "SENDING" or withdraw.notification_attempts != attempt:
            raise WithdrawNotificationStateError("Notification state changed")
        withdraw.notification_status = "FAILED"
        withdraw.notification_last_error = classification.safe_message
        withdraw.notification_message_id = None
        withdraw.notification_sent_at = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    return WithdrawNotificationResult(withdraw_id, "FAILED", attempt, None, None, classification.retryable)


def send_withdraw_notification(db, withdraw_id: int, now: datetime | None = None) -> WithdrawNotificationResult:
    now = now or datetime.now(timezone.utc)
    started = start_withdraw_notification(db, withdraw_id, now)
    try:
        withdraw = db.query(Withdraw).filter(Withdraw.id == withdraw_id).first()
        if not withdraw:
            raise WithdrawNotificationNotFoundError("Withdraw not found")
        user = db.query(User).filter(User.telegram_id == withdraw.telegram_id).first()
        telegram = send_admin_message(
            _message(withdraw, user),
            reply_markup={"inline_keyboard": [[{
                "text": "🙋 Qabul qilish",
                "callback_data": f"claim_withdraw_{withdraw.id}",
            }]]},
        )
    except (
        WithdrawNotificationNotFoundError,
        TelegramNotificationConfigError, TelegramNotificationTimeoutError,
        TelegramNotificationNetworkError, TelegramNotificationRateLimitError,
        TelegramNotificationTemporaryError, TelegramNotificationPermanentError,
        TelegramNotificationResponseError,
    ) as error:
        return _finalize_failed(db, withdraw_id, started.attempts, error)
    try:
        withdraw = _locked_withdraw(db, withdraw_id)
        if not withdraw or withdraw.notification_status != "SENDING" or withdraw.notification_attempts != started.attempts:
            raise WithdrawNotificationStateError("Notification state changed")
        withdraw.notification_status = "SENT"
        withdraw.notification_message_id = str(telegram.message_id)
        withdraw.notification_sent_at = now
        withdraw.notification_last_error = None
        db.commit()
        return WithdrawNotificationResult(withdraw.id, "SENT", started.attempts, str(telegram.message_id), now, False)
    except Exception:
        db.rollback()
        raise
