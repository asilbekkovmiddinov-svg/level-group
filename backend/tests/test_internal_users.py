from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.user import InternalUserRegister
from app.services.internal_users import (
    InternalUserServiceError,
    mark_internal_user_seen,
    register_internal_user,
)


FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeQuery:
    def __init__(self, value):
        self.value = value
        self.filter_called = False
        self.with_for_update_called = False

    def filter(self, *_):
        self.filter_called = True
        return self

    def with_for_update(self):
        self.with_for_update_called = True
        return self

    def first(self):
        return self.value


class FakeSession:
    def __init__(self, user=None, wallet=None, commit_failure=False):
        self.user = user
        self.wallet = wallet
        self.commit_failure = commit_failure
        self.commit_count = 0
        self.rollback_count = 0
        self.queries = []

    def query(self, model):
        query = FakeQuery(self.user if model is User else self.wallet)
        self.queries.append((model, query))
        return query

    def add(self, value):
        if isinstance(value, User):
            self.user = value
        elif isinstance(value, Wallet):
            self.wallet = value

    def flush(self):
        return None

    def commit(self):
        if self.commit_failure:
            raise SQLAlchemyError("commit failed")
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


class RaceSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.first_commit = True

    def commit(self):
        if self.first_commit:
            self.first_commit = False
            self.user = User(telegram_id=123456789, first_name="Other worker")
            self.wallet = Wallet(telegram_id=123456789)
            raise IntegrityError("INSERT", {}, RuntimeError("duplicate user"))
        super().commit()


def payload(**overrides):
    values = {
        "telegram_id": 123456789,
        "username": "ali",
        "first_name": "Ali",
        "last_name": "Valiyev",
    }
    values.update(overrides)
    return InternalUserRegister(**values)


def test_register_creates_user_and_wallet_in_one_commit():
    db = FakeSession()

    result = register_internal_user(db, payload(), now=FIXED_NOW)

    assert result.created is True and result.wallet_created is True
    assert db.user.telegram_id == 123456789
    assert db.user.last_name == "Valiyev"
    assert db.user.last_seen_at == FIXED_NOW
    assert db.wallet.telegram_id == 123456789
    assert db.wallet.efc_balance == 0 and db.wallet.uzs_balance == 0
    assert db.commit_count == 1 and db.rollback_count == 0
    assert all(query.with_for_update_called for _, query in db.queries)


def test_repeat_register_updates_existing_user_without_duplicate_wallet():
    user = User(telegram_id=123456789, username="old", first_name="Old")
    wallet = Wallet(telegram_id=123456789)
    db = FakeSession(user=user, wallet=wallet)

    result = register_internal_user(db, payload(username="new", first_name="New"), now=FIXED_NOW)

    assert result.created is False and result.wallet_created is False
    assert db.user.username == "new" and db.user.first_name == "New"
    assert db.wallet is wallet and db.commit_count == 1


def test_sequential_parallel_register_contract_creates_once():
    db = FakeSession()

    first = register_internal_user(db, payload(), now=FIXED_NOW)
    second = register_internal_user(db, payload(), now=FIXED_NOW)

    assert first.created is True and second.created is False
    assert first.wallet_created is True and second.wallet_created is False
    assert db.commit_count == 2


def test_register_retries_after_parallel_duplicate_user_conflict():
    db = RaceSession()

    result = register_internal_user(db, payload(), now=FIXED_NOW)

    assert result.created is False and result.wallet_created is False
    assert db.user.username == "ali"
    assert db.rollback_count == 1 and db.commit_count == 1


def test_seen_updates_existing_user_without_creating_wallet():
    user = User(telegram_id=123456789, first_name="Ali")
    db = FakeSession(user=user)

    assert mark_internal_user_seen(db, 123456789, now=FIXED_NOW) is True
    assert db.user.last_seen_at == FIXED_NOW
    assert db.wallet is None and db.commit_count == 1


def test_seen_missing_user_returns_false_without_commit():
    db = FakeSession()

    assert mark_internal_user_seen(db, 123456789, now=FIXED_NOW) is False
    assert db.commit_count == 0 and db.rollback_count == 1


def test_register_rolls_back_on_commit_failure():
    db = FakeSession(commit_failure=True)

    with pytest.raises(InternalUserServiceError):
        register_internal_user(db, payload(), now=FIXED_NOW)

    assert db.commit_count == 0 and db.rollback_count == 1
