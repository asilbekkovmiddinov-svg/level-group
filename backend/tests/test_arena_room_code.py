from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.crud import match as match_crud
from app.models.match import MatchGameType, MatchStatus
from app.routers import match as match_router
from app.services.arena_state_machine import ArenaTransitionError


def make_match(status=MatchStatus.ROOM_READY, **overrides):
    values = {
        "id": 42,
        "status": status,
        "creator_telegram_id": 1001,
        "opponent_telegram_id": 2002,
        "game_type": MatchGameType.EFOOTBALL,
        "creator_display_name": "Ali",
        "opponent_display_name": "Vali",
        "efc_amount": 100,
        "total_pool": 200,
        "winner_reward": 190,
        "scheduled_at": datetime(2026, 7, 14, 12, 0),
        "ready_window_started_at": None,
        "ready_deadline_at": None,
        "creator_ready": True,
        "opponent_ready": True,
        "room_code": None,
        "room_code_created_by": None,
        "room_code_created_at": None,
        "updated_at": datetime(2026, 7, 13, 12, 0),
        "result_type": None,
        "resolved_at": None,
        "created_at": datetime(2026, 7, 13, 12, 0),
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


def test_creator_can_store_room_code_once(monkeypatch):
    match = make_match()
    db = FakeSession()
    lock_calls = []

    def locked_match(_db, match_id):
        lock_calls.append(match_id)
        return match

    monkeypatch.setattr(match_crud, "get_match_for_update", locked_match)

    result = match_crud.create_room_code(db, 42, 1001, "  ABC-123  ")

    assert lock_calls == [42]
    assert result.room_code == "ABC-123"
    assert result.room_code_created_by == 1001
    assert isinstance(result.room_code_created_at, datetime)
    assert result.status == MatchStatus.PLAYING
    assert db.commit_count == 1


def test_opponent_cannot_store_room_code(monkeypatch):
    match = make_match()
    db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)

    with pytest.raises(ValueError, match="Faqat match yaratuvchisi"):
        match_crud.create_room_code(db, 42, 2002, "ABC-123")

    assert match.room_code is None
    assert match.status == MatchStatus.ROOM_READY
    assert db.commit_count == 0


@pytest.mark.parametrize(
    "status",
    [
        MatchStatus.WAITING_PLAYER,
        MatchStatus.WAITING_READY,
        MatchStatus.PLAYING,
        MatchStatus.TECHNICAL_REVIEW,
        MatchStatus.COMPLETED,
        MatchStatus.CANCELLED,
    ],
)
def test_room_code_is_rejected_outside_room_ready(monkeypatch, status):
    match = make_match(status=status)
    db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)

    with pytest.raises(ArenaTransitionError):
        match_crud.create_room_code(db, 42, 1001, "ABC-123")

    assert match.room_code is None
    assert db.commit_count == 0


def test_duplicate_and_parallel_submit_are_blocked(monkeypatch):
    shared_match = make_match()
    first_db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: shared_match)

    first = match_crud.create_room_code(first_db, 42, 1001, "FIRST")
    assert first.room_code == "FIRST"
    assert first_db.commit_count == 1

    second_db = FakeSession()
    with pytest.raises(ArenaTransitionError):
        match_crud.create_room_code(second_db, 42, 1001, "SECOND")
    assert shared_match.room_code == "FIRST"
    assert second_db.commit_count == 0


def test_room_code_visibility_is_participant_only():
    match = make_match(status=MatchStatus.PLAYING, room_code="PRIVATE-ROOM")

    assert match_router._participant_response(match, 1001).room_code == "PRIVATE-ROOM"
    assert match_router._participant_response(match, 2002).room_code == "PRIVATE-ROOM"
    assert match_router._participant_response(match, 9999).room_code is None


def test_creator_only_error_maps_to_http_403():
    with pytest.raises(HTTPException) as error:
        match_router._raise_match_error(
            ValueError("Faqat match yaratuvchisi Room Code kirita oladi")
        )
    assert error.value.status_code == 403
