from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.crud import match as match_crud
from app.models.match import Match
from app.models.match import MatchStatus
from app.routers import match as match_router
from app.services.arena_state_machine import (
    ALLOWED_ACTION_STATUSES,
    ArenaAction,
    ArenaTransitionError,
    ensure_action_allowed,
    ensure_evidence_not_repeated,
    ensure_ready_not_repeated,
)


def make_match(status, **overrides):
    values = {
        "id": 42,
        "status": status,
        "creator_telegram_id": 1001,
        "opponent_telegram_id": 2002,
        "creator_ready": False,
        "opponent_ready": False,
        "ready_check_started_at": None,
        "creator_result_screenshot": None,
        "opponent_result_screenshot": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeSession:
    def __init__(self):
        self.commit_count = 0
        self.refresh_count = 0

    def commit(self):
        self.commit_count += 1

    def refresh(self, _):
        self.refresh_count += 1


def test_mutating_match_query_uses_row_lock():
    match = make_match(MatchStatus.WAITING_PLAYER)

    class Query:
        def __init__(self):
            self.with_for_update_called = False

        def filter(self, *_):
            return self

        def with_for_update(self):
            self.with_for_update_called = True
            return self

        def first(self):
            return match

    class Session:
        def __init__(self):
            self.query_model = None
            self.query_result = Query()

        def query(self, model):
            self.query_model = model
            return self.query_result

    db = Session()
    assert match_crud.get_match_for_update(db, 42) is match
    assert db.query_model is Match
    assert db.query_result.with_for_update_called is True


@pytest.mark.parametrize(
    ("action", "match"),
    [
        (ArenaAction.ACCEPT, make_match(MatchStatus.WAITING_PLAYER)),
        (ArenaAction.START_READY_CHECK, make_match(MatchStatus.WAITING_READY)),
        (
            ArenaAction.MARK_READY,
            make_match(MatchStatus.WAITING_READY, ready_check_started_at=datetime(2026, 1, 1)),
        ),
        (
            ArenaAction.FINISH_READY_CHECK,
            make_match(MatchStatus.WAITING_READY, ready_check_started_at=datetime(2026, 1, 1)),
        ),
        (ArenaAction.CREATE_ROOM_CODE, make_match(MatchStatus.ROOM_READY)),
        (ArenaAction.UPLOAD_EVIDENCE, make_match(MatchStatus.PLAYING)),
        (ArenaAction.RESOLVE, make_match(MatchStatus.WAITING_ADMIN)),
        (ArenaAction.RESOLVE, make_match(MatchStatus.TECHNICAL_REVIEW)),
        (ArenaAction.CANCEL, make_match(MatchStatus.WAITING_PLAYER)),
    ],
)
def test_valid_actions_are_allowed(action, match):
    assert ensure_action_allowed(match, action) is None


@pytest.mark.parametrize("terminal_status", [MatchStatus.CANCELLED, MatchStatus.COMPLETED])
@pytest.mark.parametrize("action", list(ArenaAction))
def test_terminal_matches_reject_every_action(terminal_status, action):
    with pytest.raises(ArenaTransitionError):
        ensure_action_allowed(make_match(terminal_status), action)


def test_double_start_ready_and_evidence_are_rejected():
    started = make_match(
        MatchStatus.WAITING_READY,
        ready_check_started_at=datetime(2026, 1, 1),
    )
    with pytest.raises(ArenaTransitionError):
        ensure_action_allowed(started, ArenaAction.START_READY_CHECK)

    creator_ready = make_match(
        MatchStatus.WAITING_READY,
        ready_check_started_at=datetime(2026, 1, 1),
        creator_ready=True,
    )
    with pytest.raises(ArenaTransitionError):
        ensure_ready_not_repeated(creator_ready, 1001)

    evidence = make_match(
        MatchStatus.WAITING_ADMIN,
        creator_result_screenshot="telegram-file-id",
    )
    with pytest.raises(ArenaTransitionError):
        ensure_evidence_not_repeated(evidence, 1001)


def test_resolved_match_cannot_resolve_again_before_wallet_mutation(monkeypatch):
    match = make_match(MatchStatus.COMPLETED)
    db = FakeSession()
    wallet_mutated = False

    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)

    def mutate_wallet(**_):
        nonlocal wallet_mutated
        wallet_mutated = True

    monkeypatch.setattr(match_crud, "_take_locked_efc", mutate_wallet)

    with pytest.raises(ArenaTransitionError):
        match_crud.resolve_match(db, 42, 9001, 1001)

    assert wallet_mutated is False
    assert db.commit_count == 0


def test_cancelled_match_cannot_cancel_or_start_again_before_mutation(monkeypatch):
    match = make_match(MatchStatus.CANCELLED)
    db = FakeSession()
    wallet_mutated = False

    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)

    def mutate_wallet(**_):
        nonlocal wallet_mutated
        wallet_mutated = True

    monkeypatch.setattr(match_crud, "_unlock_efc", mutate_wallet)

    with pytest.raises(ArenaTransitionError):
        match_crud.cancel_match(db, 42, "duplicate")
    with pytest.raises(ArenaTransitionError):
        match_crud.start_ready_check(db, 42)

    assert wallet_mutated is False
    assert db.commit_count == 0


@pytest.mark.parametrize(
    "operation",
    [
        lambda db: match_crud.set_player_ready(db, 42, 1001),
        lambda db: match_crud.create_room_code(db, 42, 1001, "abc"),
        lambda db: match_crud.upload_result_screenshot(db, 42, 1001, "file-id"),
    ],
)
def test_completed_match_rejects_ready_room_and_evidence(monkeypatch, operation):
    match = make_match(MatchStatus.COMPLETED)
    db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)

    with pytest.raises(ArenaTransitionError):
        operation(db)
    assert db.commit_count == 0


def test_transition_errors_map_to_http_409():
    with pytest.raises(HTTPException) as error:
        match_router._raise_match_error(ArenaTransitionError("invalid transition"))
    assert error.value.status_code == 409


def test_every_action_has_an_explicit_server_side_status_policy():
    assert set(ALLOWED_ACTION_STATUSES) == set(ArenaAction)
    assert all(ALLOWED_ACTION_STATUSES[action] for action in ArenaAction)
