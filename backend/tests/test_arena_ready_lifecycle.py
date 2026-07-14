from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.crud import match as match_crud
from app.models.match import MatchResultType, MatchStatus
from app.services.arena_state_machine import ArenaTransitionError


FIXED_NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


def make_match(**overrides):
    values = {
        "id": 42,
        "status": MatchStatus.WAITING_READY,
        "creator_telegram_id": 1001,
        "opponent_telegram_id": 2002,
        "efc_amount": 100,
        "scheduled_at": FIXED_NOW,
        "ready_check_started_at": FIXED_NOW - timedelta(minutes=5),
        "ready_check_deadline_at": FIXED_NOW,
        "ready_window_started_at": None,
        "ready_deadline_at": None,
        "creator_ready": False,
        "opponent_ready": False,
        "creator_ready_at": None,
        "opponent_ready_at": None,
        "winner_telegram_id": None,
        "loser_telegram_id": None,
        "result_type": None,
        "cancel_reason": None,
        "resolved_at": None,
        "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeSession:
    def __init__(self):
        self.commit_count = 0
        self.refresh_count = 0

    def commit(self):
        self.commit_count += 1

    def refresh(self, _match):
        self.refresh_count += 1


def run_finish(monkeypatch, match):
    db = FakeSession()
    unlocks = []
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)
    monkeypatch.setattr(match_crud, "_unlock_efc", lambda **kwargs: unlocks.append(kwargs))
    result = match_crud.finish_ready_check(db, match.id, now=FIXED_NOW)
    return result, db, unlocks


def test_ready_window_uses_scheduled_time_as_deadline(monkeypatch):
    match = make_match(
        ready_check_started_at=None,
        ready_check_deadline_at=None,
        scheduled_at=FIXED_NOW,
    )
    db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)

    result = match_crud.start_ready_check(db, match.id, now=FIXED_NOW - timedelta(minutes=5))

    assert result.ready_check_started_at == FIXED_NOW - timedelta(minutes=5)
    assert result.ready_check_deadline_at == FIXED_NOW
    assert result.status == MatchStatus.WAITING_READY
    assert db.commit_count == 1


def test_zero_ready_cancels_and_unlocks_both_players(monkeypatch):
    match, db, unlocks = run_finish(monkeypatch, make_match())

    assert match.status == MatchStatus.CANCELLED
    assert match.result_type == MatchResultType.CANCELLED
    assert {call["telegram_id"] for call in unlocks} == {1001, 2002}
    assert db.commit_count == 1


@pytest.mark.parametrize(
    ("creator_ready", "opponent_ready"),
    [(True, False), (False, True)],
)
def test_one_ready_moves_to_technical_review_without_money_action(
    monkeypatch, creator_ready, opponent_ready
):
    match, db, unlocks = run_finish(
        monkeypatch,
        make_match(creator_ready=creator_ready, opponent_ready=opponent_ready),
    )

    assert match.status == MatchStatus.TECHNICAL_REVIEW
    assert match.winner_telegram_id is None
    assert match.loser_telegram_id is None
    assert match.result_type is None
    assert unlocks == []
    assert db.commit_count == 1


def test_both_ready_moves_to_room_ready_without_unlock(monkeypatch):
    match, db, unlocks = run_finish(
        monkeypatch,
        make_match(creator_ready=True, opponent_ready=True),
    )

    assert match.status == MatchStatus.ROOM_READY
    assert unlocks == []
    assert db.commit_count == 1


def test_double_and_parallel_finish_are_blocked_after_first_commit(monkeypatch):
    shared_match = make_match(creator_ready=True, opponent_ready=True)
    first, first_db, _ = run_finish(monkeypatch, shared_match)
    assert first.status == MatchStatus.ROOM_READY
    assert first_db.commit_count == 1

    second_db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: shared_match)
    with pytest.raises(ArenaTransitionError):
        match_crud.finish_ready_check(second_db, shared_match.id, now=FIXED_NOW)
    assert second_db.commit_count == 0


def test_marking_second_player_ready_does_not_finish_worker_lifecycle(monkeypatch):
    match = make_match(
        creator_ready=True,
        opponent_ready=False,
        ready_check_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)

    result = match_crud.set_player_ready(db, match.id, 2002)

    assert result.creator_ready is True
    assert result.opponent_ready is True
    assert result.status == MatchStatus.WAITING_READY
    assert db.commit_count == 1
