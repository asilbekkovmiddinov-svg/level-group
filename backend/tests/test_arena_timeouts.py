from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Lock
from types import SimpleNamespace

from sqlalchemy.exc import OperationalError

from app.models.match import MatchResultType, MatchStatus
from app.services import arena_timeouts
from app.services.arena_time import TASHKENT, api_tashkent_to_utc, ensure_utc


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def make_match(status=MatchStatus.WAITING_PLAYER, **overrides):
    values = {
        "id": 42,
        "status": status,
        "creator_telegram_id": 1001,
        "opponent_telegram_id": None,
        "efc_amount": Decimal("100"),
        "timeout_deadline_at": NOW - timedelta(seconds=1),
        "timeout_processed_at": None,
        "timeout_reason": None,
        "result_type": None,
        "cancel_reason": None,
        "resolved_at": None,
        "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeSession:
    def __init__(self, match=None, row_lock=None):
        self.match = match
        self.row_lock = row_lock
        self.held = False
        self.commits = 0
        self.rollbacks = 0

    def lock_match(self):
        if self.row_lock and not self.row_lock.acquire(blocking=False):
            return None
        self.held = bool(self.row_lock)
        return self.match

    def commit(self):
        self.commits += 1
        self._release()

    def rollback(self):
        self.rollbacks += 1
        self._release()

    def refresh(self, _match):
        return None

    def _release(self):
        if self.held:
            self.held = False
            self.row_lock.release()


def test_waiting_player_timeout_is_idempotent_and_unlocks_once(monkeypatch):
    match = make_match()
    db = FakeSession(match)
    unlocks = []
    monkeypatch.setattr(arena_timeouts, "_locked_match", lambda *_: match)
    monkeypatch.setattr(
        arena_timeouts.match_crud,
        "_unlock_efc",
        lambda **kwargs: unlocks.append(kwargs),
    )

    first = arena_timeouts.process_arena_timeout(db, match.id, NOW)
    replay = arena_timeouts.process_arena_timeout(db, match.id, NOW)

    assert first.outcome == "PROCESSED"
    assert replay.outcome == "SKIPPED"
    assert match.status == MatchStatus.CANCELLED
    assert match.result_type == MatchResultType.CANCELLED
    assert len(unlocks) == 1
    assert db.commits == 1


def test_room_ready_timeout_unlocks_both_participants(monkeypatch):
    match = make_match(MatchStatus.ROOM_READY, opponent_telegram_id=2002)
    db = FakeSession(match)
    unlocks = []
    monkeypatch.setattr(arena_timeouts, "_locked_match", lambda *_: match)
    monkeypatch.setattr(
        arena_timeouts.match_crud,
        "_unlock_efc",
        lambda **kwargs: unlocks.append(kwargs["telegram_id"]),
    )

    result = arena_timeouts.process_arena_timeout(db, match.id, NOW)

    assert result.outcome == "PROCESSED"
    assert match.status == MatchStatus.CANCELLED
    assert set(unlocks) == {1001, 2002}


def test_playing_and_waiting_admin_timeout_require_review_without_money(monkeypatch):
    monkeypatch.setattr(
        arena_timeouts.match_crud,
        "_unlock_efc",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not unlock")),
    )
    for status in (MatchStatus.PLAYING, MatchStatus.WAITING_ADMIN):
        match = make_match(status, opponent_telegram_id=2002)
        db = FakeSession(match)
        monkeypatch.setattr(arena_timeouts, "_locked_match", lambda *_args, item=match: item)

        result = arena_timeouts.process_arena_timeout(db, match.id, NOW)

        assert result.outcome == "PROCESSED"
        assert match.status == MatchStatus.TECHNICAL_REVIEW
        assert match.timeout_deadline_at is None


def test_parallel_workers_cannot_apply_transition_twice(monkeypatch):
    match = make_match()
    row_lock = Lock()
    unlocks = []
    monkeypatch.setattr(arena_timeouts, "_locked_match", lambda db, _id: db.lock_match())
    monkeypatch.setattr(
        arena_timeouts.match_crud,
        "_unlock_efc",
        lambda **kwargs: unlocks.append(kwargs),
    )

    def run():
        return arena_timeouts.process_arena_timeout(FakeSession(match, row_lock), match.id, NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))

    assert sum(result.outcome == "PROCESSED" for result in results) == 1
    assert len(unlocks) == 1


def test_worker_retries_are_bounded(monkeypatch):
    db = FakeSession()
    calls = []
    monkeypatch.setattr(arena_timeouts, "_due_match_ids", lambda *_: [42])

    def process(*_args):
        calls.append(1)
        if len(calls) < 3:
            raise OperationalError("statement", {}, RuntimeError("temporary"))
        return arena_timeouts.ArenaTimeoutResult(42, "PROCESSED")

    monkeypatch.setattr(arena_timeouts, "process_arena_timeout", process)
    result = arena_timeouts.run_arena_timeout_worker(db, now=NOW)

    assert result.processed == 1
    assert result.failed == 0
    assert result.retries == 2
    assert len(calls) == arena_timeouts.WORKER_MAX_ATTEMPTS


def test_tashkent_api_time_and_legacy_naive_db_time_normalize_to_utc():
    local = datetime(2026, 7, 15, 17, 0)
    explicit_local = local.replace(tzinfo=TASHKENT)

    assert api_tashkent_to_utc(local) == NOW
    assert api_tashkent_to_utc(explicit_local) == NOW
    assert ensure_utc(datetime(2026, 7, 15, 12, 0)) == NOW

