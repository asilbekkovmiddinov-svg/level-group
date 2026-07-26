from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.crud import match as match_crud
from app.models.match import ArenaNotificationDelivery, Match
from app.models.match import MatchStatus
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.services import arena_notifications
from app.services.arena_state_machine import ArenaTransitionError
from app.services.telegram_notifications import TelegramNotificationNetworkError, TelegramPhotoResult


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Wallet.__table__,
            Transaction.__table__,
            Match.__table__,
            ArenaNotificationDelivery.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    session.add(User(telegram_id=1001, first_name="Arena test"))
    session.add(Wallet(telegram_id=1001, efc_balance=Decimal("500"), locked_efc=0))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _create(db, key="arena-request-1", amount=Decimal("100")):
    return match_crud.create_match(
        db,
        creator_telegram_id=1001,
        efc_amount=amount,
        scheduled_at=datetime(2030, 1, 1),
        rules_accepted=True,
        idempotency_key=key,
    )


def test_create_replay_returns_original_without_second_efc_lock(db):
    first = _create(db)
    replay = _create(db)

    wallet = db.query(Wallet).filter(Wallet.telegram_id == 1001).one()
    assert replay.id == first.id
    assert db.query(Match).count() == 1
    assert wallet.efc_balance == Decimal("400")
    assert wallet.locked_efc == Decimal("100")


def test_active_match_guard_rejects_duplicate_create(db):
    _create(db)

    with pytest.raises(ValueError, match="faol Arena match"):
        _create(db, key="arena-request-2")

    assert db.query(Match).count() == 1


def test_creator_cancel_unlocks_efc_records_transaction_and_history_status(db):
    match = _create(db)
    match.timeout_reason = "WAITING_PLAYER_TIMEOUT"
    match.timeout_processed_at = datetime(2026, 7, 26)
    db.commit()

    cancelled = match_crud.cancel_creator_waiting_match(db, match.id, 1001)

    wallet = db.query(Wallet).filter(Wallet.telegram_id == 1001).one()
    transactions = (
        db.query(Transaction)
        .filter(Transaction.telegram_id == 1001)
        .order_by(Transaction.id)
        .all()
    )
    assert cancelled.status == MatchStatus.CANCELLED
    assert cancelled.cancel_reason == "USER_CANCELLED"
    assert cancelled.resolved_at is not None
    assert cancelled.timeout_deadline_at is None
    assert cancelled.timeout_reason is None
    assert cancelled.timeout_processed_at is None
    assert wallet.efc_balance == Decimal("500")
    assert wallet.locked_efc == Decimal("0")
    assert [transaction.type for transaction in transactions] == [
        "MATCH_LOCK",
        "MATCH_UNLOCK",
    ]

    with pytest.raises(ArenaTransitionError):
        match_crud.cancel_creator_waiting_match(db, match.id, 1001)
    assert db.query(Transaction).count() == 2


def test_creator_cancel_rejects_non_creator_and_joined_room(db):
    match = _create(db)

    with pytest.raises(ValueError, match="Faqat match yaratuvchisi"):
        match_crud.cancel_creator_waiting_match(db, match.id, 9999)

    match.opponent_telegram_id = 2002
    db.commit()
    with pytest.raises(ArenaTransitionError, match="Raqib qo‘shilgan"):
        match_crud.cancel_creator_waiting_match(db, match.id, 1001)

    wallet = db.query(Wallet).filter(Wallet.telegram_id == 1001).one()
    assert wallet.efc_balance == Decimal("400")
    assert wallet.locked_efc == Decimal("100")
    assert db.query(Transaction).count() == 1


def test_idempotency_key_rejects_changed_payload(db):
    _create(db)

    with pytest.raises(ValueError, match="boshqa request"):
        _create(db, amount=Decimal("120"))


def test_notification_retries_then_persists_sent_and_deduplicates(db, monkeypatch):
    match = _create(db)
    calls = []

    def send(_text, chat_id=None):
        calls.append(chat_id)
        if len(calls) < 3:
            raise TelegramNotificationNetworkError("temporary")
        return TelegramPhotoResult(message_id=77, chat_id=chat_id)

    monkeypatch.setattr(arena_notifications, "send_admin_message", send)

    arena_notifications.notify_arena_event(db, match, "CREATE")
    arena_notifications.notify_arena_event(db, match, "CREATE")

    delivery = db.query(ArenaNotificationDelivery).one()
    assert delivery.status == "SENT"
    assert delivery.attempts == 3
    assert delivery.message_id == "77"
    assert calls == [1001, 1001, 1001]


def test_notification_retry_is_bounded(db, monkeypatch):
    match = _create(db)
    calls = []

    def fail(_text, chat_id=None):
        calls.append(chat_id)
        raise TelegramNotificationNetworkError("temporary")

    monkeypatch.setattr(arena_notifications, "send_admin_message", fail)
    arena_notifications.notify_arena_event(db, match, "CREATE")
    arena_notifications.notify_arena_event(db, match, "CREATE")

    delivery = db.query(ArenaNotificationDelivery).one()
    assert delivery.status == "FAILED"
    assert delivery.attempts == arena_notifications.ARENA_NOTIFICATION_MAX_ATTEMPTS
    assert len(calls) == arena_notifications.ARENA_NOTIFICATION_MAX_ATTEMPTS


@pytest.mark.parametrize(
    "event_type",
    ["CREATE", "JOIN", "READY", "PLAYING", "EVIDENCE", "RESOLVE", "CANCEL"],
)
def test_arena_notification_event_contracts_are_persisted(db, monkeypatch, event_type):
    match = _create(db)
    monkeypatch.setattr(
        arena_notifications,
        "send_admin_message",
        lambda _text, chat_id=None: TelegramPhotoResult(message_id=88, chat_id=chat_id),
    )

    arena_notifications.notify_arena_event(db, match, event_type, actor_telegram_id=1001)

    delivery = db.query(ArenaNotificationDelivery).one()
    assert delivery.event_type == event_type
    assert delivery.status == "SENT"
