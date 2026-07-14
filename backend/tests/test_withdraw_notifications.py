from datetime import datetime, timezone

import pytest

from app.models.withdraw import Withdraw
from app.services.withdraw_notifications import (
    WithdrawNotificationAlreadySentError,
    WithdrawNotificationAttemptsExceededError,
    WithdrawNotificationInProgressError,
    WithdrawNotificationStateError,
    start_withdraw_notification,
)


class FakeWithdraw:
    id = 12

    def __init__(self, status="PENDING", attempts=0, last_attempt_at=None):
        self.notification_status = status
        self.notification_attempts = attempts
        self.notification_last_attempt_at = last_attempt_at
        self.notification_last_error = "old"
        self.notification_sent_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        self.notification_message_id = "old"


class FakeQuery:
    def __init__(self, withdraw):
        self.withdraw = withdraw
        self.locked = False
    def filter(self, *_): return self
    def with_for_update(self): self.locked = True; return self
    def first(self): return self.withdraw


class FakeSession:
    def __init__(self, withdraw):
        self.query_model = None
        self.query_result = FakeQuery(withdraw)
        self.commits = 0
        self.rollbacks = 0
    def query(self, model): self.query_model = model; return self.query_result
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


def test_pending_withdraw_notification_starts_with_persisted_delivery_state():
    withdraw = FakeWithdraw()
    db = FakeSession(withdraw)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = start_withdraw_notification(db, 12, now)
    assert db.query_model is Withdraw and db.query_result.locked
    assert result.status == "SENDING" and result.attempts == 1
    assert withdraw.notification_status == "SENDING"
    assert withdraw.notification_last_attempt_at == now
    assert withdraw.notification_last_error is None
    assert withdraw.notification_sent_at is None
    assert withdraw.notification_message_id is None
    assert db.commits == 1 and db.rollbacks == 0


def test_failed_and_stale_notifications_can_retry():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stale = datetime(2025, 12, 31, 23, 50, tzinfo=timezone.utc)
    for withdraw in (FakeWithdraw("FAILED", 1), FakeWithdraw("SENDING", 1, stale)):
        result = start_withdraw_notification(FakeSession(withdraw), 12, now)
        assert result.attempts == 2 and withdraw.notification_status == "SENDING"


def test_duplicate_parallel_invalid_and_attempt_limited_notifications_are_blocked():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cases = (
        (FakeWithdraw("SENT"), WithdrawNotificationAlreadySentError),
        (FakeWithdraw("SENDING", last_attempt_at=now), WithdrawNotificationInProgressError),
        (FakeWithdraw("PENDING", 5), WithdrawNotificationAttemptsExceededError),
        (FakeWithdraw("OTHER"), WithdrawNotificationStateError),
    )
    for withdraw, error in cases:
        db = FakeSession(withdraw)
        with pytest.raises(error):
            start_withdraw_notification(db, 12, now)
        assert db.commits == 0 and db.rollbacks == 1

    shared = FakeWithdraw()
    start_withdraw_notification(FakeSession(shared), 12, now)
    with pytest.raises(WithdrawNotificationInProgressError):
        start_withdraw_notification(FakeSession(shared), 12, now)
    assert shared.notification_attempts == 1
