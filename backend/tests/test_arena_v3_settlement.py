from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core import config
from app.core.database import Base, get_db
from app.core.telegram_auth import get_current_telegram_user
from app.models.arena_v3 import (
    ArenaV3AIReview, ArenaV3AIReviewStatus, ArenaV3Appeal,
    ArenaV3AppealStatus, ArenaV3Match, ArenaV3NotificationDelivery,
    ArenaV3SettlementStatus, ArenaV3Stats, ArenaV3Status,
)
from app.models.transaction import Transaction
from app.models.wallet import Wallet
from app.routers.arena_v3 import router
from app.routers.arena_v4 import router as arena_profile_router
from app.schemas.arena_v3 import ArenaV3CreateRequest, ArenaV3JoinRequest
from app.services import arena_v3_settlement as settlement
from app.services.arena_v3 import ArenaV3Conflict, ArenaV3Service


@pytest.fixture
def session_factory(monkeypatch):
    monkeypatch.setattr(config, "ARENA_V3_ENABLED", True)
    monkeypatch.setattr(config, "ARENA_V3_CREATE_ENABLED", True)
    monkeypatch.setattr(config, "ARENA_V3_SETTLEMENT_ENABLED", True)
    monkeypatch.setattr(config, "ARENA_V3_REFUND_ON_AI_FAILURE", False)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _wallet(db, player_id, *, balance=0, locked=100):
    value = Wallet(
        telegram_id=player_id,
        efc_balance=Decimal(balance),
        uzs_balance=0,
        locked_efc=Decimal(locked),
        locked_uzs=0,
    )
    db.add(value)
    return value


def _reviewed_match(db, *, owner_score=2, opponent_score=1, winner_id=1001):
    match = ArenaV3Match(
        public_id="ARV3SETTLEMENT0001",
        owner_id=1001,
        opponent_id=2002,
        owner_efootball_username="Owner",
        opponent_efootball_username="Opponent",
        stake_efc=Decimal("100"),
        total_pool_efc=Decimal("200"),
        commission_efc=Decimal("10"),
        winner_reward_efc=Decimal("190"),
        match_type="STANDARD",
        match_time_minutes=10,
        extra_time_enabled=False,
        penalties_enabled=True,
        status=ArenaV3Status.AI_REVIEW,
        settlement_status=ArenaV3SettlementStatus.NOT_STARTED,
    )
    db.add(match)
    db.flush()
    review = ArenaV3AIReview(
        match_id=match.id,
        status=ArenaV3AIReviewStatus.COMPLETED,
        detected_owner_score=owner_score,
        detected_opponent_score=opponent_score,
        winner_player_id=winner_id,
        provisional_winner_id=winner_id,
        score=f"{owner_score}-{opponent_score}",
        confidence=Decimal("0.9500"),
        reason="Winner detected",
    )
    db.add(review)
    _wallet(db, 1001)
    _wallet(db, 2002)
    db.commit()
    return match, review


def test_winner_settlement_is_atomic_idempotent_and_updates_stats(session_factory):
    db = session_factory()
    match, _ = _reviewed_match(db)
    result = settlement.settle_completed_match(db, match.id)
    assert result.status == ArenaV3Status.FINISHED
    assert result.settlement_status == ArenaV3SettlementStatus.COMPLETED
    assert result.winner_id == 1001
    assert result.loser_id == 2002
    assert db.get(Wallet, 1001).efc_balance == Decimal("190")
    assert db.get(Wallet, 1001).locked_efc == 0
    assert db.get(Wallet, 2002).efc_balance == 0
    assert db.get(Wallet, 2002).locked_efc == 0

    winner = db.get(ArenaV3Stats, 1001)
    loser = db.get(ArenaV3Stats, 2002)
    assert (winner.total_matches, winner.wins, winner.goals_for) == (1, 1, 2)
    assert winner.total_efc_won == Decimal("90")
    assert winner.win_rate == Decimal("100")
    assert (loser.losses, loser.goals_against) == (1, 2)
    assert loser.total_efc_lost == Decimal("100")
    assert {
        item.event_type for item in db.query(ArenaV3NotificationDelivery).all()
    } == {"MATCH_FINISHED", "MATCH_WON", "MATCH_LOST"}

    transaction_count = db.query(Transaction).count()
    notification_count = db.query(ArenaV3NotificationDelivery).count()
    repeated = settlement.settle_completed_match(db, match.id)
    assert repeated.id == match.id
    assert db.query(Transaction).count() == transaction_count
    assert db.query(ArenaV3NotificationDelivery).count() == notification_count


def test_draw_refunds_both_stakes_and_records_draw_stats(session_factory):
    db = session_factory()
    match, _ = _reviewed_match(
        db, owner_score=0, opponent_score=0, winner_id=None
    )
    settlement.settle_completed_match(db, match.id)
    assert match.status == ArenaV3Status.FINISHED
    assert match.settlement_status == ArenaV3SettlementStatus.REFUNDED
    assert db.get(Wallet, 1001).efc_balance == Decimal("100")
    assert db.get(Wallet, 2002).efc_balance == Decimal("100")
    assert db.get(ArenaV3Stats, 1001).draws == 1
    assert db.get(ArenaV3Stats, 2002).draws == 1


def test_settlement_failure_rolls_back_and_can_be_retried(
    session_factory, monkeypatch
):
    db = session_factory()
    match, _ = _reviewed_match(db)
    original = settlement.add_efc_balance
    monkeypatch.setattr(settlement, "add_efc_balance", lambda *args: None)
    with pytest.raises(ArenaV3Conflict):
        settlement.settle_completed_match(db, match.id)
    db.rollback()
    db.refresh(match)
    assert match.status == ArenaV3Status.AI_REVIEW
    assert match.settlement_status == ArenaV3SettlementStatus.NOT_STARTED
    assert db.get(Wallet, 1001).locked_efc == Decimal("100")
    assert db.query(Transaction).count() == 0

    monkeypatch.setattr(settlement, "add_efc_balance", original)
    assert settlement.settle_completed_match(db, match.id).status == ArenaV3Status.FINISHED


def test_cancelled_match_refund_is_idempotent(session_factory):
    db = session_factory()
    match, _ = _reviewed_match(db)
    match.status = ArenaV3Status.CANCELLED
    db.commit()
    settlement.refund_match(db, match.id, reason="MATCH_CANCELLED")
    settlement.refund_match(db, match.id, reason="MATCH_CANCELLED")
    assert db.get(Wallet, 1001).efc_balance == Decimal("100")
    assert db.get(Wallet, 2002).efc_balance == Decimal("100")
    assert db.query(Transaction).filter_by(type="ARENA_V3_REFUND").count() == 2
    assert db.query(ArenaV3NotificationDelivery).filter_by(
        event_type="REFUND_COMPLETED"
    ).count() == 2


def test_ai_conflict_opens_one_appeal_without_wallet_settlement(session_factory):
    db = session_factory()
    match, review = _reviewed_match(db)
    review.status = ArenaV3AIReviewStatus.APPEAL_REQUIRED
    review.winner_player_id = None
    db.commit()
    first = settlement.open_ai_appeal(db, match.id)
    second = settlement.open_ai_appeal(db, match.id)
    assert first.id == second.id
    assert first.status == ArenaV3AppealStatus.OPEN
    assert first.submitted_by is None
    assert db.query(ArenaV3Appeal).count() == 1
    assert match.status == ArenaV3Status.AI_REVIEW
    assert match.settlement_status == ArenaV3SettlementStatus.NOT_STARTED
    assert db.get(Wallet, 1001).locked_efc == Decimal("100")


def test_history_profile_and_result_api_use_settled_data(session_factory):
    db = session_factory()
    match, _ = _reviewed_match(db)
    settlement.settle_completed_match(db, match.id)
    db.close()
    application = FastAPI()
    application.include_router(arena_profile_router)
    application.include_router(router)

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_current_telegram_user] = lambda: SimpleNamespace(
        telegram_id=1001
    )
    client = TestClient(application)
    history = client.get("/arena/history").json()["matches"]
    assert len(history) == 1
    assert history[0]["status"] == "FINISHED"
    profile = client.get("/arena/profile").json()
    assert profile["wins"] == 1
    assert profile["goals_for"] == 2
    result = client.get(f"/arena/{match.id}/result").json()
    assert result["match"]["winner_id"] == 1001
    assert result["ai_review"]["score"] == "2-1"


def test_create_and_join_lock_stakes_with_existing_wallet_helpers(session_factory):
    db = session_factory()
    _wallet(db, 1001, balance=250, locked=0)
    _wallet(db, 2002, balance=250, locked=0)
    db.commit()
    match = ArenaV3Service(db).create_match(
        owner_id=1001,
        idempotency_key="wallet-create",
        payload=ArenaV3CreateRequest(
            owner_efootball_username="Owner",
            stake_efc=Decimal("100"),
            match_type="STANDARD",
            match_time_minutes=10,
            extra_time_enabled=False,
            penalties_enabled=True,
            rules_accepted=True,
        ),
    )
    assert db.get(Wallet, 1001).efc_balance == Decimal("150")
    assert db.get(Wallet, 1001).locked_efc == Decimal("100")
    ArenaV3Service(db).join_match(
        match_id=match.id,
        opponent_id=2002,
        idempotency_key="wallet-join",
        payload=ArenaV3JoinRequest(
            opponent_efootball_username="Opponent",
            rules_accepted=True,
        ),
    )
    assert db.get(Wallet, 2002).efc_balance == Decimal("150")
    assert db.get(Wallet, 2002).locked_efc == Decimal("100")
    assert db.query(Transaction).filter_by(type="ARENA_V3_LOCK").count() == 2


def test_configured_terminal_ai_failure_refunds_but_keeps_review_state(
    session_factory, monkeypatch
):
    db = session_factory()
    match, review = _reviewed_match(db)
    review.status = ArenaV3AIReviewStatus.FAILED
    db.commit()
    monkeypatch.setattr(config, "ARENA_V3_REFUND_ON_AI_FAILURE", True)
    settlement.handle_ai_outcome(db, match.id)
    assert match.status == ArenaV3Status.AI_REVIEW
    assert match.settlement_status == ArenaV3SettlementStatus.REFUNDED
    assert db.get(Wallet, 1001).efc_balance == Decimal("100")


def test_restart_recovery_processes_unsettled_completed_review(session_factory):
    db = session_factory()
    match, _ = _reviewed_match(db)
    processed = settlement.run_ai_outcome_queue(db)
    assert len(processed) == 1
    assert match.status == ArenaV3Status.FINISHED
