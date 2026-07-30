from datetime import datetime, timedelta, timezone
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
from app.core.database import Base
from app.models.arena_v3 import (
    ArenaV3AIReview,
    ArenaV3AIReviewStatus,
    ArenaV3Appeal,
    ArenaV3AppealStatus,
    ArenaV3Match,
    ArenaV3NotificationDelivery,
    ArenaV3SettlementStatus,
    ArenaV3Stats,
    ArenaV3Status,
)
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.arena_v3 import ArenaV3AppealDecisionRequest
from app.routers.arena_v3 import internal_router
from app.services import arena_v3_notifications as notifications
from app.services.arena_v3 import ArenaV3Conflict, ArenaV3Forbidden
from app.services.arena_v3_appeals import (
    resolve_appeal,
    submit_video_appeal,
)
from app.services.arena_v3_evidence import validate_appeal_video
from app.services.arena_v3_ranking import get_ranking
from app.services.telegram_notifications import TelegramNotificationPermanentError


@pytest.fixture
def session_factory(monkeypatch):
    monkeypatch.setattr(config, "ARENA_V3_ENABLED", True)
    monkeypatch.setattr(config, "ARENA_V3_SETTLEMENT_ENABLED", True)
    monkeypatch.setattr(config, "ARENA_V3_NOTIFICATION_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "ARENA_V3_NOTIFICATION_CLAIM_TTL_SECONDS", 300)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _conflict_match(db, suffix="1"):
    for player_id, name in ((1001, "Owner"), (2002, "Opponent")):
        db.add(User(telegram_id=player_id, first_name=name))
        db.add(Wallet(
            telegram_id=player_id,
            efc_balance=0,
            locked_efc=Decimal("100"),
            uzs_balance=0,
            locked_uzs=0,
        ))
    match = ArenaV3Match(
        public_id=f"ARV3APPEAL{suffix}",
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
    db.add(ArenaV3AIReview(
        match_id=match.id,
        status=ArenaV3AIReviewStatus.APPEAL_REQUIRED,
        reason_code="SCREENSHOT_CONFLICT",
        conflict_type="SCORE_MISMATCH",
    ))
    db.add(ArenaV3Appeal(
        match_id=match.id,
        submitted_by=None,
        reason_code="AI_SCREENSHOT_CONFLICT",
        status=ArenaV3AppealStatus.OPEN,
    ))
    db.commit()
    return match


def _submit(db, match, player_id=1001, key="upload-1"):
    return submit_video_appeal(
        db,
        match_id=match.id,
        player_id=player_id,
        payload=SimpleNamespace(reason_code="AI_CONFLICT", comment="Video proof"),
        idempotency_key=key,
        storage_key=f"appeal/{key}.mp4",
        file_hash=f"{len(key):064x}",
    )


def test_appeal_upload_is_owned_idempotent_and_duplicate_safe(session_factory):
    db = session_factory()
    match = _conflict_match(db)
    appeal = _submit(db, match)
    assert appeal.submitted_by == 1001
    assert appeal.status == ArenaV3AppealStatus.UNDER_REVIEW
    assert _submit(db, match).id == appeal.id
    with pytest.raises(ArenaV3Conflict):
        _submit(db, match, player_id=2002, key="upload-2")
    with pytest.raises(ArenaV3Forbidden):
        _submit(db, match, player_id=3003, key="upload-3")


def test_accepted_appeal_settles_once_and_clears_both_locks(session_factory):
    db = session_factory()
    match = _conflict_match(db)
    _submit(db, match)
    payload = ArenaV3AppealDecisionRequest(
        resolution="ACCEPTED",
        owner_score=3,
        opponent_score=1,
        winner_player_id=1001,
    )
    result = resolve_appeal(
        db, match_id=match.id, payload=payload, idempotency_key="decision-1"
    )
    assert result.status == ArenaV3Status.FINISHED
    assert result.settlement_status == ArenaV3SettlementStatus.COMPLETED
    assert db.get(Wallet, 1001).locked_efc == 0
    assert db.get(Wallet, 2002).locked_efc == 0
    assert db.get(Wallet, 1001).efc_balance == Decimal("190")
    repeated = resolve_appeal(
        db, match_id=match.id, payload=payload, idempotency_key="decision-1"
    )
    assert repeated.settlement_status == ArenaV3SettlementStatus.COMPLETED
    assert db.get(Wallet, 1001).efc_balance == Decimal("190")


def test_rejected_appeal_refunds_and_leaves_no_locked_wallet(session_factory):
    db = session_factory()
    match = _conflict_match(db)
    _submit(db, match)
    result = resolve_appeal(
        db,
        match_id=match.id,
        payload=ArenaV3AppealDecisionRequest(resolution="REJECTED"),
        idempotency_key="decision-reject",
    )
    assert result.status == ArenaV3Status.CANCELLED
    assert result.settlement_status == ArenaV3SettlementStatus.REFUNDED
    for player_id in (1001, 2002):
        wallet = db.get(Wallet, player_id)
        assert wallet.locked_efc == 0
        assert wallet.efc_balance == Decimal("100")


def test_appeal_video_validation_enforces_type_signature_and_limit():
    mp4 = b"\x00\x00\x00\x18ftypisom" + b"x" * 20
    metadata = validate_appeal_video("proof.mp4", "video/mp4", mp4)
    assert metadata.mime_type == "video/mp4"
    with pytest.raises(Exception, match="signature"):
        validate_appeal_video("proof.mp4", "video/mp4", b"not-video")
    with pytest.raises(Exception, match="content type"):
        validate_appeal_video("proof.mp4", "video/webm", mp4)


def test_ranking_reads_all_time_stats_and_period_match_results(session_factory):
    db = session_factory()
    now = datetime.now(timezone.utc)
    for player_id, name in ((1001, "Alpha"), (2002, "Beta")):
        db.add(User(telegram_id=player_id, first_name=name))
    db.add_all([
        ArenaV3Stats(
            player_id=1001, total_matches=3, wins=2, losses=1, draws=0,
            goals_for=6, goals_against=3, win_rate=Decimal("66.67"),
            total_efc_won=Decimal("180"), total_efc_lost=Decimal("100"),
            current_streak=1, best_streak=2,
        ),
        ArenaV3Stats(
            player_id=2002, total_matches=3, wins=1, losses=2, draws=0,
            goals_for=3, goals_against=6, win_rate=Decimal("33.33"),
            total_efc_won=Decimal("90"), total_efc_lost=Decimal("200"),
            current_streak=0, best_streak=1,
        ),
    ])
    db.add(ArenaV3Match(
        public_id="ARV3RANKING1",
        owner_id=1001,
        opponent_id=2002,
        owner_efootball_username="AlphaFC",
        opponent_efootball_username="BetaFC",
        stake_efc=Decimal("100"),
        total_pool_efc=Decimal("200"),
        commission_efc=Decimal("10"),
        winner_reward_efc=Decimal("190"),
        match_type="STANDARD",
        match_time_minutes=10,
        extra_time_enabled=False,
        penalties_enabled=True,
        status=ArenaV3Status.FINISHED,
        settlement_status=ArenaV3SettlementStatus.COMPLETED,
        winner_id=1001,
        loser_id=2002,
        owner_score=2,
        opponent_score=1,
        finished_at=now - timedelta(days=1),
    ))
    db.commit()
    all_time = get_ranking(db, period="all", limit=10, offset=0)
    weekly = get_ranking(db, period="weekly", limit=10, offset=0, now=now)
    assert [row["player_id"] for row in all_time] == [1001, 2002]
    assert weekly[0]["player_id"] == 1001
    assert weekly[0]["wins"] == 1
    assert weekly[1]["losses"] == 1


def test_notification_worker_marks_success_and_permanent_failure(
    session_factory, monkeypatch
):
    db = session_factory()
    match = _conflict_match(db)
    success = ArenaV3NotificationDelivery(
        match_id=match.id,
        recipient_id=1001,
        event_type="APPEAL_REQUIRED",
        dedup_key="success",
        status="PENDING",
    )
    db.add(success)
    db.commit()
    monkeypatch.setattr(
        notifications,
        "send_admin_message",
        lambda *args, **kwargs: SimpleNamespace(message_id=77),
    )
    assert notifications.process_next_notification(db) is True
    db.refresh(success)
    assert success.status == "SUCCESS"
    assert success.message_id == "77"

    failed = ArenaV3NotificationDelivery(
        match_id=match.id,
        recipient_id=2002,
        event_type="APPEAL_REQUIRED",
        dedup_key="failure",
        status="PENDING",
    )
    db.add(failed)
    db.commit()

    def reject(*args, **kwargs):
        raise TelegramNotificationPermanentError("blocked")

    monkeypatch.setattr(notifications, "send_admin_message", reject)
    assert notifications.process_next_notification(db) is False
    db.refresh(failed)
    assert failed.status == "FAILED"
    assert failed.attempts == config.ARENA_V3_NOTIFICATION_MAX_ATTEMPTS


def test_appeal_decision_endpoint_requires_internal_auth(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_API_KEY", "internal-secret")
    application = FastAPI()
    application.include_router(internal_router)
    client = TestClient(application)
    payload = {"resolution": "REJECTED"}
    assert client.post(
        "/internal/arena/1/appeal/decision",
        json=payload,
        headers={"Idempotency-Key": "decision"},
    ).status_code == 401
    assert client.post(
        "/internal/arena/1/appeal/decision",
        json=payload,
        headers={"X-Internal-Api-Key": "wrong", "Idempotency-Key": "decision"},
    ).status_code == 401
