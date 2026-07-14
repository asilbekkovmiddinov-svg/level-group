from contextlib import nullcontext
from types import SimpleNamespace

from app.crud.deposit import approve_deposit, claim_deposit, reject_deposit
from app.models.deposit import Deposit


class Query:
    def __init__(self, value): self.value = value; self.locked = False
    def filter(self, *_): return self
    def with_for_update(self): self.locked = True; return self
    def first(self): return self.value


class Session:
    def __init__(self, deposit): self.deposit = deposit; self.query_result = None
    def begin(self): return nullcontext()
    def query(self, model):
        assert model is Deposit
        self.query_result = Query(self.deposit)
        return self.query_result
    def flush(self): pass


def claimed_deposit(**overrides):
    values = dict(
        id=7, status="CLAIMED", claimed_by=11, claimed_at=None,
        receipt_revision=2, claimed_receipt_revision=2,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_deposit_approve_and_reject_require_claim_owner_under_row_lock():
    for operation in (
        lambda db: approve_deposit(db, 7, 22),
        lambda db: reject_deposit(db, 7, 22, "reason"),
    ):
        db = Session(claimed_deposit())
        assert operation(db) == "not_owner"
        assert db.query_result.locked is True


def test_stale_receipt_callback_and_claim_are_rejected():
    pending = claimed_deposit(status="PENDING", claimed_by=None, claimed_receipt_revision=None)
    db = Session(pending)
    assert claim_deposit(db, 7, 11, receipt_revision=1) == "receipt_replaced"
    assert pending.status == "PENDING" and db.query_result.locked is True

    db = Session(claimed_deposit(claimed_receipt_revision=1))
    assert reject_deposit(db, 7, 11, "reason") == "receipt_replaced"

