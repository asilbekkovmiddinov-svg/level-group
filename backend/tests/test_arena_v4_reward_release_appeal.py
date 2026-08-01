from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.database import Base, get_db
from app.models.arena_v3 import (
    ArenaV3Appeal,
    ArenaV3AppealStatus,
    ArenaV3Match,
    ArenaV3SettlementStatus,
    ArenaV3Status,
    ArenaV4RewardHoldStatus,
    ArenaV4SettlementOperation,
)
from app.models.transaction import Transaction
from app.models.wallet import Wallet
from app.routers.arena_v3 import require_arena_v3_access, router
from app.schemas.arena_v3 import ArenaV4AppealRequest
from app.services.arena_v3 import ArenaV3Conflict, ArenaV3Forbidden
from app.services.arena_v4_appeals import submit_v4_video_appeal
from app.services.arena_v4_reward_release import (
    release_match_reward,
    run_reward_release_queue,
)


NOW = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
VIDEO = b"\x00\x00\x00\x18ftypisom" + b"x" * 20


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _finished_match(db, *, release_at=None):
    match = ArenaV3Match(
        public_id="ARV4RELEASE0001",
        owner_id=1001,
        opponent_id=2002,
        owner_efootball_username="Player A",
        opponent_efootball_username="Player B",
        stake_efc=Decimal("500.00"),
        total_pool_efc=Decimal("1000.00"),
        commission_efc=Decimal("100.00"),
        winner_reward_efc=Decimal("900.00"),
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
        result_version=1,
        reward_hold_status=ArenaV4RewardHoldStatus.LOCKED,
        reward_release_at=release_at or NOW + timedelta(minutes=30),
        appeal_deadline_at=release_at or NOW + timedelta(minutes=30),
        has_appeal=False,
        finished_at=NOW,
        settled_at=NOW,
    )
    db.add(match)
    db.add_all([
        Wallet(
            telegram_id=1001, efc_balance=0, uzs_balance=0,
            locked_efc=0, locked_reward_efc=Decimal("900.00"), locked_uzs=0,
        ),
        Wallet(
            telegram_id=2002, efc_balance=0, uzs_balance=0,
            locked_efc=0, locked_reward_efc=0, locked_uzs=0,
        ),
    ])
    db.commit()
    return match


def _appeal(db, match, *, player_id=1001, now=None, key="appeal-1"):
    return submit_v4_video_appeal(
        db,
        match_id=match.id,
        player_id=player_id,
        payload=ArenaV4AppealRequest(reason="Wrong winner selected"),
        idempotency_key=key,
        storage_key=f"arena/v4/{match.id}/{key}.mp4",
        file_hash=f"{len(key):064x}",
        now=now or NOW + timedelta(minutes=5),
    )


def test_reward_releases_only_after_thirty_minutes(session_factory):
    db = session_factory()
    match = _finished_match(db)
    early = release_match_reward(
        db, match.id, now=NOW + timedelta(minutes=29, seconds=59)
    )
    assert early.outcome == "NOT_DUE"
    assert db.get(Wallet, 1001).efc_balance == Decimal("0.00")

    released = release_match_reward(
        db, match.id, now=NOW + timedelta(minutes=30)
    )
    assert released.outcome == "RELEASED"
    db.refresh(match)
    wallet = db.get(Wallet, 1001)
    assert wallet.locked_reward_efc == Decimal("0.00")
    assert wallet.efc_balance == Decimal("900.00")
    assert match.reward_hold_status == ArenaV4RewardHoldStatus.AVAILABLE
    operation = db.query(ArenaV4SettlementOperation).filter_by(
        operation_type="REWARD_RELEASE"
    ).one()
    assert operation.amount_efc == Decimal("900.00")
    assert db.query(Transaction).filter_by(
        type="ARENA_V4_REWARD_RELEASED"
    ).count() == 1


def test_reward_worker_is_idempotent_and_prevents_double_release(session_factory):
    db = session_factory()
    match = _finished_match(db, release_at=NOW)
    assert [item.outcome for item in run_reward_release_queue(db, now=NOW)] == [
        "RELEASED"
    ]
    assert run_reward_release_queue(db, now=NOW) == []
    assert release_match_reward(db, match.id, now=NOW).outcome == "ALREADY_RELEASED"
    wallet = db.get(Wallet, 1001)
    assert wallet.efc_balance == Decimal("900.00")
    assert db.query(ArenaV4SettlementOperation).filter_by(
        operation_type="REWARD_RELEASE"
    ).count() == 1


def test_appeal_is_pending_unique_and_keeps_match_finished(session_factory):
    db = session_factory()
    match = _finished_match(db)
    appeal = _appeal(db, match)
    assert appeal.status == ArenaV3AppealStatus.PENDING
    assert appeal.reason == "Wrong winner selected"
    assert appeal.video_storage_key.endswith("appeal-1.mp4")
    assert appeal.submitted_at.replace(tzinfo=timezone.utc) == (
        NOW + timedelta(minutes=5)
    )
    assert match.status == ArenaV3Status.FINISHED
    assert match.has_appeal is True
    assert match.reward_hold_status == ArenaV4RewardHoldStatus.LOCKED
    assert _appeal(db, match).id == appeal.id
    with pytest.raises(ArenaV3Conflict, match="already exists"):
        _appeal(db, match, player_id=2002, key="appeal-2")
    assert db.query(ArenaV3Appeal).count() == 1


def test_appeal_requires_participant_and_open_deadline(session_factory):
    db = session_factory()
    match = _finished_match(db)
    with pytest.raises(ArenaV3Forbidden):
        _appeal(db, match, player_id=3003)
    with pytest.raises(ArenaV3Conflict, match="deadline"):
        _appeal(
            db,
            match,
            now=NOW + timedelta(minutes=30),
            key="appeal-late",
        )


def test_appeal_blocks_reward_release(session_factory):
    db = session_factory()
    match = _finished_match(db)
    _appeal(db, match)
    result = release_match_reward(
        db, match.id, now=NOW + timedelta(minutes=31)
    )
    assert result.outcome == "APPEAL_BLOCKED"
    wallet = db.get(Wallet, 1001)
    assert wallet.efc_balance == Decimal("0.00")
    assert wallet.locked_reward_efc == Decimal("900.00")
    assert match.reward_hold_status == ArenaV4RewardHoldStatus.LOCKED


def test_appeal_reason_and_video_are_required_by_api(session_factory):
    with pytest.raises(ValidationError):
        ArenaV4AppealRequest(reason="   ")

    application = FastAPI()
    application.include_router(router)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[require_arena_v3_access] = lambda: SimpleNamespace(
        telegram_id=1001
    )
    client = TestClient(application)
    assert client.post(
        "/arena/1/appeal?reason=Valid+reason",
        headers={"Idempotency-Key": "missing-video"},
    ).status_code == 422
    assert client.post(
        "/arena/1/appeal",
        files={"video": ("proof.mp4", VIDEO, "video/mp4")},
        headers={"Idempotency-Key": "missing-reason"},
    ).status_code == 422
