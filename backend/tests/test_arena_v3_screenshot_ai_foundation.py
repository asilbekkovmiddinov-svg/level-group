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
from app.core.arena_internal_auth import require_arena_internal_api_key
from app.core.database import Base, get_db
from app.core.telegram_auth import get_current_telegram_user
from app.models.arena_v3 import (
    ArenaV3AIReviewStatus,
    ArenaV3Match,
    ArenaV3MatchEvent,
    ArenaV3SettlementStatus,
    ArenaV3Status,
)
from app.routers import arena_v3 as arena_router
from app.services.arena_v3 import (
    ArenaV3Conflict,
    ArenaV3Forbidden,
    ArenaV3Service,
)
from app.services.arena_v3_evidence import validate_screenshot
from app.services.arena_v3_workers import (
    complete_ai_review,
    process_screenshot_timeout,
    retry_ai_review,
    start_ai_review,
)


NOW = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)
PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x02\x00\x00\x00\x03"
    b"\x08\x02\x00\x00\x00"
)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def playing_match(db, **overrides):
    values = {
        "public_id": "ARV3SCREENSHOT01",
        "owner_id": 1001,
        "opponent_id": 2002,
        "owner_efootball_username": "Owner",
        "opponent_efootball_username": "Opponent",
        "stake_efc": Decimal("100"),
        "total_pool_efc": Decimal("200"),
        "commission_efc": Decimal("10"),
        "winner_reward_efc": Decimal("190"),
        "match_type": "STANDARD",
        "match_time_minutes": 10,
        "extra_time_enabled": False,
        "penalties_enabled": True,
        "status": ArenaV3Status.WAITING_SCREENSHOT,
        "settlement_status": ArenaV3SettlementStatus.NOT_STARTED,
        "playing_started_at": NOW,
        "screenshot_started_at": NOW,
        "screenshot_deadline_at": NOW + timedelta(seconds=300),
        "version": 4,
    }
    values.update(overrides)
    match = ArenaV3Match(**values)
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


def upload(service, match_id, player_id, key):
    return service.upload_screenshot(
        match_id=match_id,
        player_id=player_id,
        idempotency_key=key,
        storage_key=f"arena/{match_id}/{player_id}.png",
        file_hash=f"{player_id:064d}",
        mime_type="image/png",
        file_size=len(PNG),
        width=2,
        height=3,
        now=NOW + timedelta(seconds=10),
    )


def test_screenshot_validation_and_metadata():
    metadata = validate_screenshot("result.png", "image/png", PNG)
    assert metadata.width == 2
    assert metadata.height == 3
    assert metadata.file_size == len(PNG)
    with pytest.raises(Exception, match="PNG or JPEG"):
        validate_screenshot("result.txt", "text/plain", b"bad")


def test_upload_permissions_duplicate_and_repository_listing(session_factory):
    db = session_factory()
    match = playing_match(db)
    service = ArenaV3Service(db)
    screenshot = upload(service, match.id, 1001, "owner")
    assert screenshot.player_id == 1001
    assert service.list_screenshots(match_id=match.id, player_id=2002) == [screenshot]
    assert db.query(ArenaV3MatchEvent).filter_by(
        match_id=match.id, event_type="SCREENSHOT_UPLOADED"
    ).count() == 1

    with pytest.raises(ArenaV3Conflict, match="already uploaded"):
        upload(service, match.id, 1001, "owner-duplicate")
    with pytest.raises(ArenaV3Forbidden):
        upload(service, match.id, 9999, "outsider")
    with pytest.raises(ArenaV3Forbidden):
        service.list_screenshots(match_id=match.id, player_id=9999)


def test_upload_rejects_wrong_state_and_expired_window(session_factory):
    db = session_factory()
    match = playing_match(db, status=ArenaV3Status.PLAYING)
    with pytest.raises(ArenaV3Conflict, match="not accepting"):
        upload(ArenaV3Service(db), match.id, 1001, "wrong-state")

    match.status = ArenaV3Status.WAITING_SCREENSHOT
    match.screenshot_deadline_at = NOW
    db.commit()
    with pytest.raises(ArenaV3Conflict, match="expired"):
        upload(ArenaV3Service(db), match.id, 1001, "expired")


@pytest.mark.parametrize("screenshot_count", [1, 2])
def test_timeout_with_evidence_queues_ai_review(session_factory, screenshot_count):
    db = session_factory()
    match = playing_match(db)
    service = ArenaV3Service(db)
    upload(service, match.id, 1001, "owner")
    if screenshot_count == 2:
        upload(service, match.id, 2002, "opponent")

    result = process_screenshot_timeout(
        db, match.id, now=NOW + timedelta(seconds=301)
    )
    db.refresh(match)
    assert result.outcome == "PROCESSED"
    assert result.screenshot_count == screenshot_count
    assert match.status == ArenaV3Status.AI_REVIEW
    review = service.repository.get_latest_ai_review(match.id)
    assert review.status == ArenaV3AIReviewStatus.PENDING
    assert review.owner_screenshot_id is not None
    assert (review.opponent_screenshot_id is not None) == (screenshot_count == 2)
    assert db.query(ArenaV3MatchEvent).filter_by(
        match_id=match.id, event_type="SCREENSHOT_TIMEOUT"
    ).count() == 1


def test_timeout_without_evidence_cancels_without_wallet_action(session_factory):
    db = session_factory()
    match = playing_match(db)
    result = process_screenshot_timeout(
        db, match.id, now=NOW + timedelta(seconds=301)
    )
    db.refresh(match)
    assert result.status == "CANCELLED"
    assert match.status == ArenaV3Status.CANCELLED
    assert match.cancel_reason == "NO_SCREENSHOTS_TIMEOUT"
    assert ArenaV3Service(db).repository.get_latest_ai_review(match.id) is None


@pytest.mark.parametrize("match_time_minutes", [6, 8, 10, 12, 15])
def test_match_duration_opens_5_minute_screenshot_window(
    session_factory, match_time_minutes
):
    db = session_factory()
    match = playing_match(
        db,
        status=ArenaV3Status.PLAYING,
        match_time_minutes=match_time_minutes,
        screenshot_started_at=NOW + timedelta(minutes=match_time_minutes),
        screenshot_deadline_at=(
            NOW + timedelta(minutes=match_time_minutes, seconds=300)
        ),
    )

    before = process_screenshot_timeout(
        db,
        match.id,
        now=NOW + timedelta(minutes=match_time_minutes, seconds=-1),
    )
    assert before.outcome == "NOT_DUE"
    assert match.status == ArenaV3Status.PLAYING

    opened = process_screenshot_timeout(
        db, match.id, now=NOW + timedelta(minutes=match_time_minutes)
    )
    assert opened.outcome == "WINDOW_OPENED"
    assert match.status == ArenaV3Status.WAITING_SCREENSHOT
    assert (
        match.screenshot_deadline_at - match.screenshot_started_at
    ).total_seconds() == 300


def test_ai_queue_start_complete_failure_and_retry(session_factory):
    db = session_factory()
    match = playing_match(db)
    upload(ArenaV3Service(db), match.id, 1001, "owner")
    process_screenshot_timeout(db, match.id, now=NOW + timedelta(seconds=301))

    review = start_ai_review(db, match.id)
    assert review.status == ArenaV3AIReviewStatus.RUNNING
    assert review.attempt_count == 1
    failed = complete_ai_review(db, review.id, succeeded=False)
    assert failed.status == ArenaV3AIReviewStatus.FAILED
    queued = retry_ai_review(db, review.id)
    assert queued.status == ArenaV3AIReviewStatus.PENDING
    running = start_ai_review(db, match.id)
    assert running.status == ArenaV3AIReviewStatus.RUNNING
    assert running.attempt_count == 2
    completed = complete_ai_review(db, review.id, succeeded=True)
    assert completed.status == ArenaV3AIReviewStatus.COMPLETED
    events = [
        item.event_type for item in db.query(ArenaV3MatchEvent)
        .filter_by(match_id=match.id).all()
    ]
    assert events.count("AI_STARTED") == 2
    assert events.count("AI_COMPLETED") == 2


@pytest.fixture
def api(session_factory, monkeypatch):
    actor = {"telegram_id": 1001}
    application = FastAPI()
    application.include_router(arena_router.router)
    application.include_router(arena_router.internal_router)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_current_telegram_user] = lambda: SimpleNamespace(
        telegram_id=actor["telegram_id"]
    )
    application.dependency_overrides[require_arena_internal_api_key] = lambda: None
    monkeypatch.setattr(config, "ARENA_V3_ENABLED", True)
    monkeypatch.setattr(config, "ARENA_V3_AI_ENABLED", True)
    monkeypatch.setattr(arena_router, "upload_object", lambda *args: None)
    monkeypatch.setattr(arena_router, "delete_object", lambda *args: None)
    db = session_factory()
    api_now = datetime.now(timezone.utc)
    match = playing_match(
        db,
        status=ArenaV3Status.WAITING_SCREENSHOT,
        playing_started_at=api_now,
        screenshot_started_at=api_now,
        screenshot_deadline_at=api_now + timedelta(seconds=300),
    )
    match_id = match.id
    db.close()
    return TestClient(application), actor, match_id, session_factory


def test_screenshot_and_internal_ai_api(api):
    client, actor, match_id, session_factory = api
    response = client.post(
        f"/arena/{match_id}/upload-screenshot",
        files={"file": ("result.png", PNG, "image/png")},
        headers={"Idempotency-Key": "api-upload"},
    )
    assert response.status_code == 200
    assert response.json()["width"] == 2
    assert len(client.get(f"/arena/{match_id}/screenshots").json()["screenshots"]) == 1
    assert client.post(
        f"/arena/{match_id}/upload-screenshot",
        files={"file": ("result.png", PNG, "image/png")},
        headers={"Idempotency-Key": "api-duplicate"},
    ).status_code == 409

    actor["telegram_id"] = 9999
    assert client.get(f"/arena/{match_id}/screenshots").status_code == 403
    db = session_factory()
    process_screenshot_timeout(
        db, match_id, now=datetime.now(timezone.utc) + timedelta(seconds=301)
    )
    db.close()
    started = client.post(f"/internal/arena/{match_id}/start-ai")
    assert started.status_code == 200
    assert started.json()["status"] == "RUNNING"


def test_v2_routes_are_absent_from_sprint5_routers():
    paths = {
        route.path for route in [
            *arena_router.router.routes,
            *arena_router.internal_router.routes,
        ]
    }
    assert all(not path.startswith("/matches") for path in paths)


def test_internal_ai_endpoint_requires_internal_auth(monkeypatch):
    application = FastAPI()
    application.include_router(arena_router.internal_router)
    monkeypatch.setattr(config, "INTERNAL_API_KEY", "expected-secret")
    response = TestClient(application).post("/internal/arena/1/start-ai")
    assert response.status_code == 401
