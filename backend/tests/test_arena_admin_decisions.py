from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.crud import match as match_crud
from app.models.match import (
    MatchAdminDecision,
    MatchResultType,
    MatchStatus,
)
from app.schemas.match import MatchAdminResolve
from app.services.arena_state_machine import ArenaTransitionError


def make_match(status=MatchStatus.WAITING_ADMIN, **overrides):
    values = {
        "id": 42,
        "status": status,
        "creator_telegram_id": 1001,
        "opponent_telegram_id": 2002,
        "creator_ready": False,
        "opponent_ready": False,
        "efc_amount": Decimal("100"),
        "winner_reward": Decimal("190"),
        "winner_telegram_id": None,
        "loser_telegram_id": None,
        "result_type": None,
        "admin_telegram_id": None,
        "admin_comment": None,
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


def prepare_winner_mocks(monkeypatch, match):
    calls = {"take": [], "add": [], "winner_stats": [], "loser_stats": []}
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)
    monkeypatch.setattr(
        match_crud, "_take_locked_efc", lambda **kwargs: calls["take"].append(kwargs)
    )
    monkeypatch.setattr(
        match_crud, "_add_efc", lambda **kwargs: calls["add"].append(kwargs)
    )
    monkeypatch.setattr(
        match_crud,
        "_update_winner_stats",
        lambda db, telegram_id, reward: calls["winner_stats"].append(
            (telegram_id, reward)
        ),
    )
    monkeypatch.setattr(
        match_crud,
        "_update_loser_stats",
        lambda db, telegram_id, amount: calls["loser_stats"].append(
            (telegram_id, amount)
        ),
    )
    return calls


@pytest.mark.parametrize(
    ("decision", "winner", "loser"),
    [
        (MatchAdminDecision.PLAYER_1_WIN, 1001, 2002),
        (MatchAdminDecision.PLAYER_2_WIN, 2002, 1001),
    ],
)
def test_player_win_decisions_apply_existing_payout_flow(
    monkeypatch, decision, winner, loser
):
    match = make_match()
    db = FakeSession()
    calls = prepare_winner_mocks(monkeypatch, match)

    result = match_crud.resolve_match(
        db, 42, 9001, decision=decision, admin_comment="reviewed"
    )

    assert [call["telegram_id"] for call in calls["take"]] == [1001, 2002]
    assert calls["add"][0]["telegram_id"] == winner
    assert calls["add"][0]["amount"] == Decimal("190")
    assert calls["winner_stats"] == [(winner, Decimal("190"))]
    assert calls["loser_stats"] == [(loser, Decimal("100"))]
    assert result.winner_telegram_id == winner
    assert result.result_type == MatchResultType.NORMAL
    assert result.status == MatchStatus.COMPLETED
    assert db.commit_count == 1


def test_technical_win_uses_ready_player_when_winner_is_omitted(monkeypatch):
    match = make_match(
        status=MatchStatus.TECHNICAL_REVIEW,
        creator_ready=True,
        opponent_ready=False,
    )
    db = FakeSession()
    calls = prepare_winner_mocks(monkeypatch, match)

    result = match_crud.resolve_match(
        db, 42, 9001, decision=MatchAdminDecision.TECHNICAL_WIN
    )

    assert calls["add"][0]["telegram_id"] == 1001
    assert result.winner_telegram_id == 1001
    assert result.result_type == MatchResultType.TECHNICAL
    assert result.status == MatchStatus.COMPLETED


def test_refund_unlocks_both_stakes_without_payout(monkeypatch):
    match = make_match()
    db = FakeSession()
    unlocks = []
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)
    monkeypatch.setattr(
        match_crud, "_unlock_efc", lambda **kwargs: unlocks.append(kwargs)
    )

    result = match_crud.resolve_match(
        db, 42, 9001, decision=MatchAdminDecision.REFUND
    )

    assert [call["telegram_id"] for call in unlocks] == [1001, 2002]
    assert result.result_type == MatchResultType.REFUND
    assert result.winner_telegram_id is None
    assert result.status == MatchStatus.COMPLETED
    assert db.commit_count == 1


def test_cancel_uses_existing_cancel_unlock_flow(monkeypatch):
    match = make_match()
    db = FakeSession()
    unlocks = []
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)
    monkeypatch.setattr(
        match_crud, "_unlock_efc", lambda **kwargs: unlocks.append(kwargs)
    )

    result = match_crud.resolve_match(
        db,
        42,
        9001,
        decision=MatchAdminDecision.CANCEL,
        admin_comment="invalid match",
    )

    assert [call["telegram_id"] for call in unlocks] == [1001, 2002]
    assert result.status == MatchStatus.CANCELLED
    assert result.result_type == MatchResultType.CANCELLED
    assert result.cancel_reason == "invalid match"
    assert db.commit_count == 1


def test_legacy_winner_contract_remains_supported(monkeypatch):
    payload = MatchAdminResolve.model_validate(
        {"admin_telegram_id": 9001, "winner_telegram_id": 2002}
    )
    assert payload.decision is None

    match = make_match()
    db = FakeSession()
    calls = prepare_winner_mocks(monkeypatch, match)
    result = match_crud.resolve_match(db, 42, 9001, 2002)
    assert calls["add"][0]["telegram_id"] == 2002
    assert result.status == MatchStatus.COMPLETED


def test_double_and_parallel_resolve_do_not_repeat_wallet_mutation(monkeypatch):
    shared_match = make_match()
    first_db = FakeSession()
    calls = prepare_winner_mocks(monkeypatch, shared_match)

    match_crud.resolve_match(
        first_db, 42, 9001, decision=MatchAdminDecision.PLAYER_1_WIN
    )
    assert first_db.commit_count == 1
    assert len(calls["take"]) == 2

    second_db = FakeSession()
    with pytest.raises(ArenaTransitionError):
        match_crud.resolve_match(
            second_db, 42, 9001, decision=MatchAdminDecision.PLAYER_2_WIN
        )
    assert len(calls["take"]) == 2
    assert second_db.commit_count == 0


def test_arena_wallet_helpers_delegate_to_existing_wallet_services(monkeypatch):
    db = SimpleNamespace()
    wallet = SimpleNamespace(efc_balance=Decimal("250"))
    calls = []
    transactions = []
    monkeypatch.setattr(
        match_crud,
        "confirm_locked_efc",
        lambda session, telegram_id, amount: calls.append(
            ("confirm", telegram_id, amount)
        )
        or wallet,
    )
    monkeypatch.setattr(
        match_crud,
        "unlock_efc_balance",
        lambda session, telegram_id, amount: calls.append(
            ("unlock", telegram_id, amount)
        )
        or wallet,
    )
    monkeypatch.setattr(
        match_crud,
        "add_efc_balance",
        lambda session, telegram_id, amount: calls.append(
            ("add", telegram_id, amount)
        )
        or wallet,
    )
    monkeypatch.setattr(
        match_crud,
        "create_transaction",
        lambda **kwargs: transactions.append(kwargs),
    )

    match_crud._take_locked_efc(db, 1001, Decimal("100"), "spend")
    match_crud._unlock_efc(db, 1001, Decimal("100"), "refund")
    match_crud._add_efc(db, 1001, Decimal("190"), "reward")

    assert calls == [
        ("confirm", 1001, Decimal("100")),
        ("unlock", 1001, Decimal("100")),
        ("add", 1001, Decimal("190")),
    ]
    assert [item["type"] for item in transactions] == [
        "MATCH_SPEND",
        "MATCH_UNLOCK",
        "MATCH_REWARD",
    ]
    assert all(item["commit"] is False for item in transactions)
    assert all(isinstance(item["balance_after"], Decimal) for item in transactions)
