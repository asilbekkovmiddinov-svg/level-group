from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from threading import Barrier, Lock
from types import SimpleNamespace

from app.crud import match as match_crud
from app.models.match import MatchStatus


class LockedSession:
    def __init__(self, match_lock=None, wallet_locks=None, wallets=None, match=None):
        self.match_lock = match_lock
        self.wallet_locks = wallet_locks or {}
        self.wallets = wallets or {}
        self.match = match
        self.held = []
        self.commits = 0

    def lock_match(self):
        self.match_lock.acquire()
        self.held.append(self.match_lock)
        return self.match

    def lock_wallet(self, telegram_id):
        lock = self.wallet_locks[telegram_id]
        lock.acquire()
        self.held.append(lock)
        return self.wallets[telegram_id]

    def add(self, _value):
        return None

    def commit(self):
        self.commits += 1
        self._release()

    def rollback(self):
        self._release()

    def refresh(self, _value):
        return None

    def _release(self):
        while self.held:
            self.held.pop().release()


def test_parallel_create_serializes_creator_wallet_lock(monkeypatch):
    barrier = Barrier(2)
    wallet = SimpleNamespace(efc_balance=Decimal("100"), locked_efc=Decimal("0"))
    wallet_lock = Lock()
    sessions = []

    monkeypatch.setattr(
        match_crud,
        "get_wallet_for_update",
        lambda db, telegram_id: db.lock_wallet(telegram_id),
    )

    def create():
        db = LockedSession(wallet_locks={1001: wallet_lock}, wallets={1001: wallet})
        sessions.append(db)
        barrier.wait()
        try:
            return match_crud.create_match(
                db, 1001, Decimal("80"), datetime(2030, 1, 1), rules_accepted=True
            )
        except ValueError as error:
            db.rollback()
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))

    assert sum(not isinstance(result, str) for result in results) == 1
    assert results.count("EFC balans yetarli emas") == 1
    assert wallet.efc_balance == Decimal("20")
    assert wallet.locked_efc == Decimal("80")
    assert sum(db.commits for db in sessions) == 1


def test_parallel_join_serializes_match_before_opponent_wallet_lock(monkeypatch):
    barrier = Barrier(2)
    match = SimpleNamespace(
        id=42,
        status=MatchStatus.WAITING_PLAYER,
        creator_telegram_id=1001,
        opponent_telegram_id=None,
        efc_amount=Decimal("50"),
        scheduled_at=datetime(2030, 1, 1),
        updated_at=None,
    )
    match_lock = Lock()
    wallets = {
        2002: SimpleNamespace(efc_balance=Decimal("100"), locked_efc=Decimal("0")),
        3003: SimpleNamespace(efc_balance=Decimal("100"), locked_efc=Decimal("0")),
    }
    wallet_locks = {telegram_id: Lock() for telegram_id in wallets}

    monkeypatch.setattr(match_crud, "get_match_for_update", lambda db, _match_id: db.lock_match())
    monkeypatch.setattr(
        match_crud,
        "get_wallet_for_update",
        lambda db, telegram_id: db.lock_wallet(telegram_id),
    )

    def join(telegram_id):
        db = LockedSession(match_lock, wallet_locks, wallets, match)
        barrier.wait()
        try:
            return match_crud.accept_match(db, 42, telegram_id, rules_accepted=True)
        except ValueError as error:
            db.rollback()
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(join, (2002, 3003)))

    assert sum(not isinstance(result, str) for result in results) == 1
    assert sum("ACCEPT action is not allowed" in result for result in results if isinstance(result, str)) == 1
    assert match.status == MatchStatus.WAITING_READY
    assert match.opponent_telegram_id in {2002, 3003}
    winner_wallet = wallets[match.opponent_telegram_id]
    loser_id = 3003 if match.opponent_telegram_id == 2002 else 2002
    assert winner_wallet.locked_efc == Decimal("50")
    assert wallets[loser_id].locked_efc == Decimal("0")
