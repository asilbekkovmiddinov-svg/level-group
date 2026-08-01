from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.database import Base
from app.models.arena_v3 import (
    ArenaV3Appeal,
    ArenaV3AppealStatus,
    ArenaV3Match,
    ArenaV3NotificationDelivery,
    ArenaV3SettlementStatus,
    ArenaV3Stats,
    ArenaV3Status,
    ArenaV4AdminReview,
    ArenaV4AdminReviewStatus,
    ArenaV4AppealReviewAction,
    ArenaV4ResultRevision,
    ArenaV4ResultType,
    ArenaV4RewardHoldStatus,
    ArenaV4ReviewType,
    ArenaV4SettlementOperation,
    ArenaV4SettlementOperationStatus,
)
from app.models.transaction import Transaction
from app.models.wallet import Wallet
from app.schemas.arena_v3 import (
    ArenaV4AdminDecisionRequest,
    ArenaV4AppealRequest,
    ArenaV4AppealReviewRequest,
)
from app.services.arena_v3 import ArenaV3Conflict
from app.services.arena_v4_admin_review import ArenaV4AdminReviewService
from app.services.arena_v4_appeal_review import ArenaV4AppealReviewService
from app.services.arena_v4_appeals import submit_v4_video_appeal
from app.services import arena_v4_settlement


NOW = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _settled_winner_match(db):
    match = ArenaV3Match(
        public_id="ARV4APPEALREVIEW1",
        owner_id=1001,
        opponent_id=2002,
        owner_efootball_username="Player A",
        opponent_efootball_username="Player B",
        stake_efc=Decimal("500.00"),
        total_pool_efc=Decimal("1000.00"),
        commission_efc=Decimal("0.00"),
        winner_reward_efc=Decimal("0.00"),
        match_type="STANDARD",
        match_time_minutes=10,
        extra_time_enabled=False,
        penalties_enabled=True,
        status=ArenaV3Status.WAITING_ADMIN,
        settlement_status=ArenaV3SettlementStatus.NOT_STARTED,
        result_version=0,
        version=7,
    )
    db.add(match)
    db.flush()
    review = ArenaV4AdminReview(
        match_id=match.id,
        review_type=ArenaV4ReviewType.INITIAL,
        status=ArenaV4AdminReviewStatus.CLAIMED,
        result_version=0,
        assigned_admin_id=9001,
        expected_match_version=7,
        claimed_at=NOW,
    )
    db.add(review)
    db.add_all([
        Wallet(
            telegram_id=1001, efc_balance=0, uzs_balance=0,
            locked_efc=500, locked_reward_efc=0, locked_uzs=0,
        ),
        Wallet(
            telegram_id=2002, efc_balance=0, uzs_balance=0,
            locked_efc=500, locked_reward_efc=0, locked_uzs=0,
        ),
    ])
    db.commit()
    ArenaV4AdminReviewService(db).submit_decision(
        review_id=review.id,
        admin_id=9001,
        payload=ArenaV4AdminDecisionRequest(
            admin_id=9001,
            owner_score=2,
            opponent_score=1,
            reason="Initial score",
        ),
        idempotency_key="initial-score",
    )
    db.refresh(match)
    return match


def _open_and_claim_appeal(db, match):
    appeal = submit_v4_video_appeal(
        db,
        match_id=match.id,
        player_id=2002,
        payload=ArenaV4AppealRequest(reason="Score is incorrect"),
        idempotency_key="appeal-submit",
        storage_key=f"arena/v4/{match.id}/appeal.mp4",
        file_hash="a" * 64,
        now=match.finished_at.replace(tzinfo=timezone.utc) + timedelta(minutes=5),
    )
    review = (
        db.query(ArenaV4AdminReview)
        .filter_by(match_id=match.id, review_type=ArenaV4ReviewType.APPEAL)
        .one()
    )
    ArenaV4AdminReviewService(db).claim(
        review_id=review.id, admin_id=9002
    )
    return appeal, review


def _resolve(db, review, action, *, scores=None, key="appeal-resolution"):
    owner_score, opponent_score = scores or (None, None)
    return ArenaV4AppealReviewService(db).submit(
        review_id=review.id,
        admin_id=9002,
        payload=ArenaV4AppealReviewRequest(
            admin_id=9002,
            action=action,
            owner_score=owner_score,
            opponent_score=opponent_score,
            reason="Video reviewed",
        ),
        idempotency_key=key,
    )


def test_keep_result_resolves_appeal_and_unlocks_reward(session_factory):
    db = session_factory()
    match = _settled_winner_match(db)
    appeal, review = _open_and_claim_appeal(db, match)
    initial_version = match.result_version

    _resolve(db, review, ArenaV4AppealReviewAction.KEEP_RESULT)
    db.refresh(match)
    db.refresh(appeal)

    assert match.result_version == initial_version
    assert match.current_result_type == ArenaV4ResultType.PLAYER_A_WIN
    assert match.reward_hold_status == ArenaV4RewardHoldStatus.AVAILABLE
    assert db.get(Wallet, 1001).efc_balance == Decimal("900.00")
    assert db.get(Wallet, 1001).locked_reward_efc == Decimal("0.00")
    assert appeal.status == ArenaV3AppealStatus.RESOLVED
    assert appeal.resolution == ArenaV4AppealReviewAction.KEEP_RESULT.value
    assert db.query(ArenaV3NotificationDelivery).filter_by(
        event_type="APPEAL_RESOLVED"
    ).count() == 2
    assert db.query(ArenaV3NotificationDelivery).filter_by(
        event_type="REWARD_RELEASED"
    ).count() == 1


def test_update_score_auto_detects_new_winner_and_rolls_back(session_factory):
    db = session_factory()
    match = _settled_winner_match(db)
    _, review = _open_and_claim_appeal(db, match)

    _resolve(
        db,
        review,
        ArenaV4AppealReviewAction.UPDATE_SCORE,
        scores=(1, 3),
    )
    db.refresh(match)

    assert match.owner_score == 1
    assert match.opponent_score == 3
    assert match.current_result_type == ArenaV4ResultType.PLAYER_B_WIN
    assert match.winner_id == 2002
    assert match.loser_id == 1001
    assert match.result_version == 2
    assert match.reward_hold_status == ArenaV4RewardHoldStatus.AVAILABLE
    assert db.get(Wallet, 1001).efc_balance == Decimal("0.00")
    assert db.get(Wallet, 2002).efc_balance == Decimal("900.00")
    assert db.query(ArenaV4SettlementOperation).filter_by(
        result_version=1,
        status=ArenaV4SettlementOperationStatus.REVERSED,
    ).count() == 4
    revision = db.query(ArenaV4ResultRevision).filter_by(version=2).one()
    assert revision.previous_winner_id == 1001
    assert revision.new_winner_id == 2002
    assert revision.previous_owner_score == 2
    assert revision.new_opponent_score == 3


def test_update_score_auto_detects_draw_and_recalculates_stats(session_factory):
    db = session_factory()
    match = _settled_winner_match(db)
    _, review = _open_and_claim_appeal(db, match)

    with pytest.raises(ValueError, match="Equal scores are not allowed"):
        _resolve(
            db, review, ArenaV4AppealReviewAction.UPDATE_SCORE, scores=(2, 2)
        )


def test_cancel_match_rolls_back_competitive_stats(session_factory):
    db = session_factory()
    match = _settled_winner_match(db)
    _, review = _open_and_claim_appeal(db, match)

    _resolve(db, review, ArenaV4AppealReviewAction.CANCEL_MATCH)

    assert match.current_result_type == ArenaV4ResultType.CANCEL
    assert match.cancel_reason == "APPEAL_ADMIN_CANCEL"
    assert match.winner_id is None
    assert db.get(Wallet, 1001).efc_balance == Decimal("500.00")
    assert db.get(Wallet, 2002).efc_balance == Decimal("500.00")
    for player_id in (1001, 2002):
        stats = db.get(ArenaV3Stats, player_id)
        assert stats.total_matches == 0
        assert stats.wins == stats.losses == stats.draws == 0
        assert stats.goals_for == stats.goals_against == 0


def test_appeal_resolution_is_idempotent_and_blocks_second_action(
    session_factory,
):
    db = session_factory()
    match = _settled_winner_match(db)
    _, review = _open_and_claim_appeal(db, match)
    first = _resolve(db, review, ArenaV4AppealReviewAction.KEEP_RESULT)
    counts = (
        db.query(Transaction).count(),
        db.query(ArenaV4SettlementOperation).count(),
        db.query(ArenaV4ResultRevision).count(),
    )
    replay = _resolve(db, review, ArenaV4AppealReviewAction.KEEP_RESULT)
    assert replay.id == first.id
    assert counts == (
        db.query(Transaction).count(),
        db.query(ArenaV4SettlementOperation).count(),
        db.query(ArenaV4ResultRevision).count(),
    )
    with pytest.raises(ArenaV3Conflict, match="already resolved"):
        _resolve(
            db,
            review,
            ArenaV4AppealReviewAction.UPDATE_SCORE,
            scores=(0, 4),
            key="different-resolution",
        )
    assert match.result_version == 1


def test_revision_failure_rolls_back_every_change(session_factory, monkeypatch):
    db = session_factory()
    match = _settled_winner_match(db)
    appeal, review = _open_and_claim_appeal(db, match)
    before_transactions = db.query(Transaction).count()
    monkeypatch.setattr(
        arena_v4_settlement,
        "add_locked_reward_efc",
        lambda *args: None,
    )

    with pytest.raises(ArenaV3Conflict, match="locked"):
        _resolve(
            db,
            review,
            ArenaV4AppealReviewAction.UPDATE_SCORE,
            scores=(0, 2),
        )

    db.refresh(match)
    db.refresh(appeal)
    db.refresh(review)
    assert match.result_version == 1
    assert match.current_result_type == ArenaV4ResultType.PLAYER_A_WIN
    assert match.winner_id == 1001
    assert db.get(Wallet, 1001).locked_reward_efc == Decimal("900.00")
    assert appeal.status == ArenaV3AppealStatus.UNDER_REVIEW
    assert review.status == ArenaV4AdminReviewStatus.CLAIMED
    assert db.query(Transaction).count() == before_transactions
