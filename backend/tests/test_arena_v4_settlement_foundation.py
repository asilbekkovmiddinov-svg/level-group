from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.database import Base
from app.models.arena_v3 import (
    ArenaV3Match,
    ArenaV3SettlementStatus,
    ArenaV3Stats,
    ArenaV3Status,
    ArenaV4AdminReview,
    ArenaV4AdminReviewStatus,
    ArenaV4ResultRevision,
    ArenaV4ResultType,
    ArenaV4RewardHoldStatus,
    ArenaV4ReviewType,
    ArenaV4SettlementOperation,
)
from app.models.transaction import Transaction
from app.models.wallet import Wallet
from app.schemas.arena_v3 import (
    ArenaV4AdminCancelRequest,
    ArenaV4AdminDecisionRequest,
)
from app.services.arena_v3 import ArenaV3Conflict
from app.services.arena_v4_admin_review import ArenaV4AdminReviewService
from app.services import arena_v4_settlement


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _foundation(db):
    match = ArenaV3Match(
        public_id="ARV4SETTLEMENT0001",
        owner_id=1001,
        opponent_id=2002,
        owner_efootball_username="Player A",
        opponent_efootball_username="Player B",
        stake_efc=Decimal("500.00"),
        total_pool_efc=Decimal("1000.00"),
        commission_efc=Decimal("50.00"),
        winner_reward_efc=Decimal("950.00"),
        match_type="STANDARD",
        match_time_minutes=10,
        extra_time_enabled=False,
        penalties_enabled=True,
        status=ArenaV3Status.WAITING_ADMIN,
        settlement_status=ArenaV3SettlementStatus.NOT_STARTED,
        result_version=0,
        version=6,
    )
    db.add(match)
    db.flush()
    review = ArenaV4AdminReview(
        match_id=match.id,
        review_type=ArenaV4ReviewType.INITIAL,
        status=ArenaV4AdminReviewStatus.CLAIMED,
        result_version=0,
        assigned_admin_id=9999,
        expected_match_version=6,
        claimed_at=datetime.now(timezone.utc),
    )
    db.add(review)
    db.add_all([
        Wallet(
            telegram_id=1001,
            efc_balance=Decimal("0.00"),
            uzs_balance=0,
            locked_efc=Decimal("500.00"),
            locked_reward_efc=0,
            locked_uzs=0,
        ),
        Wallet(
            telegram_id=2002,
            efc_balance=Decimal("0.00"),
            uzs_balance=0,
            locked_efc=Decimal("500.00"),
            locked_reward_efc=0,
            locked_uzs=0,
        ),
    ])
    db.commit()
    return match, review


def _decide(db, review, decision, *, key="decision-1", reason="Verified"):
    if decision == ArenaV4ResultType.CANCEL:
        payload = ArenaV4AdminCancelRequest(admin_id=9999, reason=reason)
        return ArenaV4AdminReviewService(db).submit_cancel(
            review_id=review.id,
            admin_id=9999,
            payload=payload,
            idempotency_key=key,
        )
    scores = {
        ArenaV4ResultType.PLAYER_A_WIN: (2, 1),
        ArenaV4ResultType.PLAYER_B_WIN: (1, 2),
        ArenaV4ResultType.DRAW: (2, 2),
    }
    owner_score, opponent_score = scores[decision]
    payload = ArenaV4AdminDecisionRequest(
        admin_id=9999,
        owner_score=owner_score,
        opponent_score=opponent_score,
        reason=reason,
    )
    return ArenaV4AdminReviewService(db).submit_decision(
        review_id=review.id,
        admin_id=9999,
        payload=payload,
        idempotency_key=key,
    )


@pytest.mark.parametrize(
    ("decision", "winner_id", "loser_id"),
    [
        (ArenaV4ResultType.PLAYER_A_WIN, 1001, 2002),
        (ArenaV4ResultType.PLAYER_B_WIN, 2002, 1001),
    ],
)
def test_winner_settlement_uses_ten_percent_fee_and_locked_reward(
    session_factory, decision, winner_id, loser_id
):
    db = session_factory()
    match, review = _foundation(db)
    _decide(db, review, decision)
    db.refresh(match)

    assert match.status == ArenaV3Status.FINISHED
    assert match.current_result_type == decision
    assert match.result_version == 1
    assert match.current_decision_id == review.id
    assert match.initial_decision_id == review.id
    assert match.total_pool_efc == Decimal("1000.00")
    assert match.commission_efc == Decimal("100.00")
    assert match.winner_reward_efc == Decimal("900.00")
    assert match.winner_id == winner_id
    assert match.loser_id == loser_id
    assert match.reward_hold_status == ArenaV4RewardHoldStatus.LOCKED
    assert int((match.reward_release_at - match.settled_at).total_seconds()) == 1800
    assert match.appeal_deadline_at == match.reward_release_at
    assert match.has_appeal is False

    winner = db.get(Wallet, winner_id)
    loser = db.get(Wallet, loser_id)
    assert winner.efc_balance == Decimal("0.00")
    assert winner.locked_efc == Decimal("0.00")
    assert winner.locked_reward_efc == Decimal("900.00")
    assert loser.efc_balance == Decimal("0.00")
    assert loser.locked_efc == Decimal("0.00")
    assert loser.locked_reward_efc == Decimal("0.00")

    operations = db.query(ArenaV4SettlementOperation).all()
    assert {item.operation_type for item in operations} == {
        "STAKE_CONSUME", "REWARD_LOCK", "PLATFORM_FEE"
    }
    assert len(operations) == 4
    fee = next(item for item in operations if item.operation_type == "PLATFORM_FEE")
    assert fee.amount_efc == Decimal("100.00")
    locked_tx = db.query(Transaction).filter_by(
        type="ARENA_V4_REWARD_LOCKED"
    ).one()
    assert locked_tx.status == "LOCKED"
    assert locked_tx.balance_before == locked_tx.balance_after == Decimal("0.00")
    assert db.query(ArenaV4ResultRevision).one().version == 1


def test_draw_refunds_both_players_with_zero_fee_and_draw_stats(session_factory):
    db = session_factory()
    match, review = _foundation(db)
    _decide(db, review, ArenaV4ResultType.DRAW)

    assert match.status == ArenaV3Status.FINISHED
    assert match.settlement_status == ArenaV3SettlementStatus.REFUNDED
    assert match.commission_efc == Decimal("0.00")
    assert match.winner_reward_efc == Decimal("0.00")
    assert match.reward_hold_status == ArenaV4RewardHoldStatus.LOCKED
    for player_id in (1001, 2002):
        wallet = db.get(Wallet, player_id)
        assert wallet.efc_balance == Decimal("0.00")
        assert wallet.locked_reward_efc == Decimal("500.00")
        assert wallet.locked_efc == Decimal("0.00")
        assert db.get(ArenaV3Stats, player_id).draws == 1
    assert {
        item.operation_type for item in db.query(ArenaV4SettlementOperation)
    } == {"STAKE_REFUND", "PLATFORM_FEE"}
    assert db.query(ArenaV4SettlementOperation).filter_by(
        operation_type="PLATFORM_FEE"
    ).one().amount_efc == Decimal("0.00")


def test_cancel_refunds_without_competitive_stats(session_factory):
    db = session_factory()
    match, review = _foundation(db)
    _decide(db, review, ArenaV4ResultType.CANCEL)

    assert match.status == ArenaV3Status.FINISHED
    assert match.current_result_type == ArenaV4ResultType.CANCEL
    assert match.cancel_reason == "ADMIN_CANCEL"
    assert match.commission_efc == Decimal("0.00")
    assert db.query(ArenaV3Stats).count() == 0
    assert db.get(Wallet, 1001).locked_reward_efc == Decimal("500.00")
    assert db.get(Wallet, 2002).locked_reward_efc == Decimal("500.00")


def test_decision_replay_is_idempotent_and_second_decision_is_blocked(
    session_factory,
):
    db = session_factory()
    match, review = _foundation(db)
    first = _decide(db, review, ArenaV4ResultType.PLAYER_A_WIN)
    counts = (
        db.query(Transaction).count(),
        db.query(ArenaV4SettlementOperation).count(),
        db.query(ArenaV4ResultRevision).count(),
    )
    replay = _decide(db, review, ArenaV4ResultType.PLAYER_A_WIN)
    assert replay.id == first.id
    assert counts == (
        db.query(Transaction).count(),
        db.query(ArenaV4SettlementOperation).count(),
        db.query(ArenaV4ResultRevision).count(),
    )
    with pytest.raises(ArenaV3Conflict, match="already final"):
        _decide(
            db,
            review,
            ArenaV4ResultType.PLAYER_B_WIN,
            key="decision-2",
        )
    assert match.result_version == 1


def test_settlement_failure_rolls_back_decision_wallet_and_ledger(
    session_factory, monkeypatch
):
    db = session_factory()
    match, review = _foundation(db)
    monkeypatch.setattr(arena_v4_settlement, "add_locked_reward_efc", lambda *args: None)

    with pytest.raises(ArenaV3Conflict, match="locked reward"):
        _decide(db, review, ArenaV4ResultType.PLAYER_A_WIN)

    db.refresh(match)
    db.refresh(review)
    assert match.status == ArenaV3Status.WAITING_ADMIN
    assert match.settlement_status == ArenaV3SettlementStatus.NOT_STARTED
    assert match.result_version == 0
    assert review.status == ArenaV4AdminReviewStatus.CLAIMED
    assert review.decision is None
    assert db.get(Wallet, 1001).locked_efc == Decimal("500.00")
    assert db.get(Wallet, 2002).locked_efc == Decimal("500.00")
    assert db.query(Transaction).count() == 0
    assert db.query(ArenaV4SettlementOperation).count() == 0
    assert db.query(ArenaV4ResultRevision).count() == 0
