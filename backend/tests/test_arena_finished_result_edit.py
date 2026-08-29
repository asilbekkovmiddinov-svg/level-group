from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.arena_v3 import (
    ArenaV3SettlementStatus,
    ArenaV3Status,
    ArenaV4ResultType,
    ArenaV4RewardHoldStatus,
)
from app.routers.arena_finished_result_edit import ArenaFinishedResultEditRequest
from app.services import arena_finished_result_edit as service
from app.services.arena_v3 import ArenaV3Conflict


class FakeDB:
    def __init__(self):
        self.commit_count = 0
        self.refresh_count = 0

    def commit(self):
        self.commit_count += 1

    def refresh(self, _match):
        self.refresh_count += 1


class FakeRepository:
    def __init__(self, match):
        self.match = match
        self.revisions = []
        self.events = []

    def get_match_for_update(self, match_id):
        return self.match if self.match.id == match_id else None

    def add_result_revision(self, revision):
        self.revisions.append(revision)
        return revision

    def add_event(self, event):
        self.events.append(event)
        return event


def make_match(**overrides):
    values = dict(
        id=42,
        status=ArenaV3Status.FINISHED,
        match_type="STANDARD",
        ticket_cost=10,
        flow_version=5,
        owner_id=1001,
        opponent_id=2002,
        owner_score=3,
        opponent_score=1,
        current_result_type=ArenaV4ResultType.PLAYER_A_WIN,
        result_version=1,
        result_source="ADMIN",
        winner_id=1001,
        loser_id=2002,
        cancel_reason=None,
        stake_efc=Decimal("0.00"),
        total_pool_efc=Decimal("0.00"),
        commission_efc=Decimal("0.00"),
        winner_reward_efc=Decimal("0.00"),
        reward_hold_status=ArenaV4RewardHoldStatus.NONE,
        reward_release_at=None,
        settlement_status=ArenaV3SettlementStatus.COMPLETED,
        updated_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def run(monkeypatch, match, a, b):
    db = FakeDB()
    repo = FakeRepository(match)
    recalculated = []
    monkeypatch.setattr(service, "_recalculate_player_stats", lambda _repo, player_id: recalculated.append(player_id))
    result = service.revise_finished_ticket_result(
        db,
        repository=repo,
        match_id=42,
        admin_id=9001,
        owner_score=a,
        opponent_score=b,
        reason="ADMIN_TEST_CORRECTION",
    )
    return result, db, repo, recalculated


def test_finished_result_can_flip_winner_and_recalculate_stats(monkeypatch):
    match = make_match()
    result, db, repo, recalculated = run(monkeypatch, match, 1, 4)
    assert result.current_result_type == ArenaV4ResultType.PLAYER_B_WIN
    assert result.winner_id == 2002
    assert result.loser_id == 1001
    assert recalculated == [1001, 2002]
    assert db.commit_count == 1
    assert len(repo.revisions) == 1
    assert len(repo.events) == 1


def test_finished_v5_result_can_be_corrected_to_draw(monkeypatch):
    payload = ArenaFinishedResultEditRequest(admin_id=9001, owner_score=1, opponent_score=1)
    assert payload.owner_score == payload.opponent_score == 1

    match = make_match()
    result, db, repo, recalculated = run(monkeypatch, match, 1, 1)
    assert result.current_result_type == ArenaV4ResultType.DRAW
    assert result.winner_id is None
    assert result.loser_id is None
    assert result.owner_score == result.opponent_score == 1
    assert recalculated == [1001, 2002]
    assert db.commit_count == 1
    assert len(repo.revisions) == 1
    assert repo.revisions[0].new_result_type == ArenaV4ResultType.DRAW.value


def test_non_finished_match_is_rejected(monkeypatch):
    match = make_match(status=ArenaV3Status.WAITING_ADMIN)
    db = FakeDB(); repo = FakeRepository(match)
    with pytest.raises(ArenaV3Conflict, match="Only a finished"):
        service.revise_finished_ticket_result(db, repository=repo, match_id=42, admin_id=9001, owner_score=1, opponent_score=4, reason="test")
    assert db.commit_count == 0


def test_same_result_is_rejected_without_duplicate_audit(monkeypatch):
    match = make_match(); db = FakeDB(); repo = FakeRepository(match)
    with pytest.raises(ArenaV3Conflict, match="must differ"):
        service.revise_finished_ticket_result(db, repository=repo, match_id=42, admin_id=9001, owner_score=3, opponent_score=1, reason="test")
    assert db.commit_count == 0
    assert repo.revisions == []
    assert repo.events == []


def test_non_ticket_match_is_rejected(monkeypatch):
    match = make_match(ticket_cost=0); db = FakeDB(); repo = FakeRepository(match)
    with pytest.raises(ArenaV3Conflict, match="ticket Arena"):
        service.revise_finished_ticket_result(db, repository=repo, match_id=42, admin_id=9001, owner_score=1, opponent_score=4, reason="test")
    assert db.commit_count == 0
