from datetime import datetime, timezone

from app.models.deposit import Deposit
from app.services.deposit_notifications import start_deposit_receipt_notification


class FakeDeposit:
    id = 7
    receipt_object_key = "private"
    receipt_notification_status = "PENDING"
    receipt_notification_attempts = 0
    receipt_notification_last_attempt_at = None
    receipt_notification_last_error = "old"
    receipt_notification_sent_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    receipt_notification_message_id = "old"


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
