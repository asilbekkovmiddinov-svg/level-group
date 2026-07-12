from datetime import datetime, timezone

from app.models.deposit import Deposit
from app.services.deposit_notifications import start_deposit_receipt_notification
from app.services.deposit_notifications import DepositNotificationAlreadySentError, DepositNotificationAttemptsExceededError, DepositNotificationInProgressError, DepositNotificationNotFoundError, DepositNotificationStateError, DepositReceiptMissingError


class FakeDeposit:
    id = 7
    receipt_object_key = "private"
    receipt_notification_status = "PENDING"
    receipt_notification_attempts = 0
    receipt_notification_last_attempt_at = None
    receipt_notification_last_error = "old"
    receipt_notification_sent_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    receipt_notification_message_id = "old"

    def __init__(self, status="PENDING", attempts=0, receipt=True, last_attempt_at=None):
        self.id = 7; self.receipt_object_key = "private" if receipt else None; self.receipt_notification_status = status; self.receipt_notification_attempts = attempts; self.receipt_notification_last_attempt_at = last_attempt_at; self.receipt_notification_last_error = "old"; self.receipt_notification_sent_at = datetime(2020, 1, 1, tzinfo=timezone.utc); self.receipt_notification_message_id = "old"


class FakeQuery:
    def __init__(self, deposit): self.deposit = deposit; self.filter_called = False; self.with_for_update_called = False
    def filter(self, *_): self.filter_called = True; return self
    def with_for_update(self): self.with_for_update_called = True; return self
    def first(self): return self.deposit


class FakeSession:
    def __init__(self, deposit): self.query_model = None; self.query_result = FakeQuery(deposit); self.commit_count = 0; self.rollback_count = 0; self.commit_failure = False
    def query(self, model): self.query_model = model; return self.query_result
    def commit(self):
        if self.commit_failure: raise RuntimeError("commit failure")
        self.commit_count += 1
    def rollback(self): self.rollback_count += 1


def test_pending_receipt_notification_starts():
    deposit, db = FakeDeposit(), FakeSession(FakeDeposit())
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = start_deposit_receipt_notification(db, deposit.id, now=now)
    assert db.query_model is Deposit and db.query_result.filter_called and db.query_result.with_for_update_called
    assert db.query_result.deposit.receipt_notification_status == "SENDING"
    assert db.query_result.deposit.receipt_notification_attempts == 1
    assert db.query_result.deposit.receipt_notification_last_attempt_at == now
    assert db.query_result.deposit.receipt_notification_last_error is None
    assert db.query_result.deposit.receipt_notification_sent_at is None
    assert db.query_result.deposit.receipt_notification_message_id is None
    assert db.commit_count == 1 and db.rollback_count == 0
    assert result.status == "SENDING" and result.attempts == 1 and result.message_id is None and result.sent_at is None

def test_failed_and_stale_sending_restart():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for deposit in (FakeDeposit("FAILED", 1), FakeDeposit("SENDING", 1, last_attempt_at=datetime(2025, 12, 31, 23, 50, tzinfo=timezone.utc))):
        db = FakeSession(deposit); start_deposit_receipt_notification(db, 7, now)
        assert deposit.receipt_notification_status == "SENDING" and deposit.receipt_notification_attempts == 2 and deposit.receipt_notification_last_error is None and db.commit_count == 1

def test_active_sending_sent_and_attempt_limit_are_blocked():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cases = [(FakeDeposit("SENDING", last_attempt_at=now), DepositNotificationInProgressError), (FakeDeposit("SENT"), DepositNotificationAlreadySentError), (FakeDeposit("PENDING", 5), DepositNotificationAttemptsExceededError)]
    for deposit, error in cases:
        db = FakeSession(deposit)
        try: start_deposit_receipt_notification(db, 7, now)
        except error: pass
        else: assert False
        assert db.commit_count == 0 and db.rollback_count == 1

def test_missing_not_found_unknown_and_parallel_contract():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for deposit, error in ((FakeDeposit(receipt=False), DepositReceiptMissingError), (None, DepositNotificationNotFoundError), (FakeDeposit("OTHER"), DepositNotificationStateError)):
        db = FakeSession(deposit)
        try: start_deposit_receipt_notification(db, 7, now)
        except error: pass
        else: assert False
    shared = FakeDeposit(); start_deposit_receipt_notification(FakeSession(shared), 7, now)
    try: start_deposit_receipt_notification(FakeSession(shared), 7, now)
    except DepositNotificationInProgressError: pass
    else: assert False
    assert shared.receipt_notification_attempts == 1

def test_commit_failure_rolls_back_fake_state():
    deposit = FakeDeposit(); db = FakeSession(deposit); db.commit_failure = True
    try: start_deposit_receipt_notification(db, 7, datetime(2026, 1, 1, tzinfo=timezone.utc))
    except RuntimeError: pass
    else: assert False
    assert db.rollback_count == 1 and deposit.receipt_notification_status == "PENDING" and deposit.receipt_notification_attempts == 0
