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
    ArenaV3MatchEvent,
    ArenaV3NotificationDelivery,
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
from app.services.arena_v4_result_confirmation import confirm_result
from app.services import arena_v4_result_confirmation


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
    assert db.query(ArenaV3NotificationDelivery).filter_by(
        event_type="REWARD_RELEASED", recipient_id=1001
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
    assert db.query(ArenaV3NotificationDelivery).filter_by(
        event_type="REWARD_RELEASED"
    ).count() == 1


def test_reward_worker_recovers_from_process_restart(session_factory):
    setup_db = session_factory()
    match = _finished_match(setup_db, release_at=NOW)
    match_id = match.id
    setup_db.close()

    restarted_db = session_factory()
    assert [item.outcome for item in run_reward_release_queue(
        restarted_db, now=NOW
    )] == ["RELEASED"]
    restarted_db.close()

    next_restart_db = session_factory()
    assert run_reward_release_queue(next_restart_db, now=NOW) == []
    db_match = next_restart_db.get(ArenaV3Match, match_id)
    assert db_match is not None
    assert db_match.reward_hold_status == ArenaV4RewardHoldStatus.AVAILABLE
    assert next_restart_db.get(Wallet, 1001).efc_balance == Decimal("900.00")
    next_restart_db.close()


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


def test_both_players_confirm_to_release_reward_early(session_factory):
    db = session_factory()
    match = _finished_match(db)

    first = confirm_result(
        db, match_id=match.id, player_id=1001,
        idempotency_key="confirm-a", now=NOW + timedelta(minutes=2),
    )
    assert first["owner_confirmed"] is True
    assert first["opponent_confirmed"] is False
    assert first["reward_released"] is False
    assert db.get(Wallet, 1001).locked_reward_efc == Decimal("900.00")

    second = confirm_result(
        db, match_id=match.id, player_id=2002,
        idempotency_key="confirm-b", now=NOW + timedelta(minutes=3),
    )
    assert second["both_confirmed"] is True
    assert second["reward_released"] is True
    assert second["reward_hold_status"] == ArenaV4RewardHoldStatus.AVAILABLE
    wallet = db.get(Wallet, 1001)
    assert wallet.locked_reward_efc == Decimal("0.00")
    assert wallet.efc_balance == Decimal("900.00")
    db.refresh(match)
    assert match.appeal_deadline_at.replace(tzinfo=timezone.utc) == (
        NOW + timedelta(minutes=3)
    )


def test_confirmation_is_idempotent_and_one_player_cannot_unlock(session_factory):
    db = session_factory()
    match = _finished_match(db)
    confirm_result(
        db, match_id=match.id, player_id=1001,
        idempotency_key="confirm-a", now=NOW + timedelta(minutes=1),
    )
    replay = confirm_result(
        db, match_id=match.id, player_id=1001,
        idempotency_key="different-key", now=NOW + timedelta(minutes=2),
    )
    assert replay["both_confirmed"] is False
    assert db.get(Wallet, 1001).efc_balance == Decimal("0.00")
    assert db.query(ArenaV3MatchEvent).filter_by(
        event_type="V4_RESULT_CONFIRMED"
    ).count() == 1


def test_confirmation_and_appeal_are_mutually_exclusive(session_factory):
    db = session_factory()
    match = _finished_match(db)
    confirm_result(
        db, match_id=match.id, player_id=1001,
        idempotency_key="confirm-a", now=NOW + timedelta(minutes=1),
    )
    with pytest.raises(ArenaV3Conflict, match="no longer be appealed"):
        _appeal(db, match, player_id=1001, key="appeal-after-confirm")


def test_appeal_blocks_result_confirmation(session_factory):
    db = session_factory()
    match = _finished_match(db)
    _appeal(db, match, player_id=2002, key="appeal-before-confirm")
    with pytest.raises(ArenaV3Conflict, match="blocked by an appeal"):
        confirm_result(
            db, match_id=match.id, player_id=1001,
            idempotency_key="confirm-after-appeal",
        )


def test_second_confirmation_rolls_back_if_release_fails(
    session_factory, monkeypatch,
):
    db = session_factory()
    match = _finished_match(db)
    confirm_result(
        db, match_id=match.id, player_id=1001,
        idempotency_key="confirm-a",
    )
    def fail_release(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        arena_v4_result_confirmation, "release_match_reward", fail_release
    )
    with pytest.raises(RuntimeError, match="boom"):
        confirm_result(
            db, match_id=match.id, player_id=2002,
            idempotency_key="confirm-b",
        )
    db.expire_all()
    stored = db.get(ArenaV3Match, match.id)
    assert stored.owner_result_confirmed_at is not None
    assert stored.opponent_result_confirmed_at is None
    assert stored.reward_hold_status == ArenaV4RewardHoldStatus.LOCKED


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


def test_result_confirmation_api_requires_idempotency_and_participant(
    session_factory,
):
    db = session_factory()
    match = _finished_match(db)
    match_id = match.id
    db.close()
    application = FastAPI()
    application.include_router(router)
    current_player = {"telegram_id": 1001}

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[require_arena_v3_access] = lambda: (
        SimpleNamespace(**current_player)
    )
    client = TestClient(application)
    assert client.post(f"/arena/{match_id}/confirm-result").status_code == 400
    response = client.post(
        f"/arena/{match_id}/confirm-result",
        headers={"Idempotency-Key": "confirm-api-a"},
    )
    assert response.status_code == 200
    assert response.json()["owner_confirmed"] is True
    assert response.json()["both_confirmed"] is False
    current_player["telegram_id"] = 3003
    assert client.post(
        f"/arena/{match_id}/confirm-result",
        headers={"Idempotency-Key": "confirm-outsider"},
    ).status_code == 403
