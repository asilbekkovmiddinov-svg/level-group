import io
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.database import Base
from app.core.database import get_db
from app.core.arena_v3_migrations import run_arena_v3_migrations
from app.models.arena_v3 import (
    ArenaV3AIReview, ArenaV3AIReviewStatus, ArenaV3EvidenceStatus,
    ArenaV3Match, ArenaV3MatchScreenshot, ArenaV3SettlementStatus, ArenaV3Status,
)
from app.services import arena_v3_workers as workers
from app.services.arena_v3_ai import (
    ArenaV3AnalysisError, ScreenshotOCRResult, normalize_ocr_result,
    validate_image, winner_for_scores,
)
from app.services.object_storage import DownloadedObject
from app.routers.arena_v3 import internal_router


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


def _png():
    output = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, "PNG")
    return output.getvalue()


def _queued(db, *, screenshots=2):
    match = ArenaV3Match(
        public_id="ARV3AI000000001", owner_id=1001, opponent_id=2002,
        owner_efootball_username="Owner.FC", opponent_efootball_username="Opponent FC",
        stake_efc=Decimal("100"), total_pool_efc=Decimal("200"),
        commission_efc=Decimal("10"), winner_reward_efc=Decimal("190"),
        match_type="STANDARD", match_time_minutes=10, extra_time_enabled=False,
        penalties_enabled=True, status=ArenaV3Status.AI_REVIEW,
        settlement_status=ArenaV3SettlementStatus.NOT_STARTED,
    )
    db.add(match)
    db.flush()
    rows = []
    for index, player_id in enumerate((1001, 2002)[:screenshots], 1):
        row = ArenaV3MatchScreenshot(
            match_id=match.id, player_id=player_id, storage_key=f"shot-{index}",
            file_hash=f"{index:064d}", mime_type="image/png", file_size=len(_png()),
            width=20, height=20, validation_status=ArenaV3EvidenceStatus.PENDING,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    review = ArenaV3AIReview(
        match_id=match.id, status=ArenaV3AIReviewStatus.PENDING,
        owner_screenshot_id=rows[0].id,
        opponent_screenshot_id=rows[1].id if len(rows) > 1 else None,
    )
    db.add(review)
    db.commit()
    return match, review


class FakeAnalyzer:
    def __init__(self, results):
        self.results = iter(results)

    def analyze(self, content, mime_type):
        validate_image(content)
        return next(self.results), "response-id"


def _ocr(owner_goals=2, opponent_goals=1, **values):
    defaults = dict(
        is_match_history=True, player_1_username="owner fc",
        player_2_username="OPPONENT.FC", player_1_goals=owner_goals,
        player_2_goals=opponent_goals, match_result="completed",
        confidence=0.94, reason="Visible Match History result",
    )
    defaults.update(values)
    return ScreenshotOCRResult(**defaults)


def test_image_validation_rejects_corrupt_data():
    with pytest.raises(ArenaV3AnalysisError, match="corrupted"):
        validate_image(b"\x89PNG\r\n\x1a\nbroken")


def test_username_matching_handles_orientation_and_rejects_mismatch():
    result = normalize_ocr_result(
        _ocr(player_1_username="Opponent FC", player_2_username="Owner.FC",
             player_1_goals=1, player_2_goals=3),
        owner_username="owner fc", opponent_username="opponent.fc",
    )
    assert (result.owner_score, result.opponent_score) == (3, 1)
    with pytest.raises(ArenaV3AnalysisError) as error:
        normalize_ocr_result(
            _ocr(player_1_username="Someone else"),
            owner_username="Owner", opponent_username="Opponent",
        )
    assert error.value.code == "USERNAME_MISMATCH"


def test_worker_completes_matching_results_and_detects_winner(db, monkeypatch):
    match, review = _queued(db)
    content = _png()
    monkeypatch.setattr(
        workers, "download_object_bytes",
        lambda _: DownloadedObject(content, "image/png", len(content)),
    )
    result = workers.process_next_ai_review(
        db, analyzer=FakeAnalyzer([_ocr(), _ocr()])
    )
    assert result.id == review.id
    assert result.status == ArenaV3AIReviewStatus.COMPLETED
    assert result.winner_player_id == match.owner_id
    assert result.score == "2-1"
    assert str(result.confidence) == "0.9400"
    assert match.status == ArenaV3Status.AI_REVIEW


def test_worker_marks_conflicting_screenshots_for_appeal(db, monkeypatch):
    _, review = _queued(db)
    content = _png()
    monkeypatch.setattr(
        workers, "download_object_bytes",
        lambda _: DownloadedObject(content, "image/png", len(content)),
    )
    result = workers.process_next_ai_review(
        db, analyzer=FakeAnalyzer([_ocr(2, 1), _ocr(1, 2)])
    )
    assert result.id == review.id
    assert result.status == ArenaV3AIReviewStatus.APPEAL_REQUIRED
    assert result.conflict_type == "SCORE_MISMATCH"
    assert result.winner_player_id is None


@pytest.mark.parametrize(
    "ocr,code",
    [
        (_ocr(is_match_history=False), "NOT_MATCH_HISTORY"),
        (_ocr(player_1_username="intruder"), "USERNAME_MISMATCH"),
    ],
)
def test_worker_fails_invalid_analysis(db, monkeypatch, ocr, code):
    _, review = _queued(db, screenshots=1)
    content = _png()
    monkeypatch.setattr(
        workers, "download_object_bytes",
        lambda _: DownloadedObject(content, "image/png", len(content)),
    )
    result = workers.process_next_ai_review(db, analyzer=FakeAnalyzer([ocr]))
    assert result.id == review.id
    assert result.status == ArenaV3AIReviewStatus.FAILED
    assert result.reason_code == code


def test_draw_has_no_winner():
    match = type("Match", (), {"owner_id": 1, "opponent_id": 2})()
    assert winner_for_scores(match, 0, 0) == (None, "DRAW")


def test_migration_adds_ai_result_columns_to_existing_table():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE arena_ai_reviews"))
        connection.execute(text(
            "CREATE TABLE arena_ai_reviews ("
            "id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL, status VARCHAR(32) NOT NULL,"
            "attempt_count INTEGER NOT NULL, created_at DATETIME NOT NULL)"
        ))
    run_arena_v3_migrations(engine)
    columns = {item["name"] for item in inspect(engine).get_columns("arena_ai_reviews")}
    assert {"winner_player_id", "score", "reason"} <= columns


def test_internal_ai_result_requires_auth_and_returns_contract(db, monkeypatch):
    match, review = _queued(db, screenshots=1)
    review.status = ArenaV3AIReviewStatus.COMPLETED
    review.winner_player_id = match.owner_id
    review.score = "2-1"
    review.confidence = Decimal("0.9400")
    review.reason = "Owner Win"
    db.commit()
    application = FastAPI()
    application.include_router(internal_router)

    def override_db():
        yield db

    application.dependency_overrides[get_db] = override_db
    client = TestClient(application)
    assert client.get(f"/internal/arena/{match.id}/ai-result").status_code == 401
    monkeypatch.setattr("app.core.config.INTERNAL_API_KEY", "secret")
    response = client.get(
        f"/internal/arena/{match.id}/ai-result",
        headers={"X-Internal-API-Key": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["score"] == "2-1"
    assert response.json()["winner_player_id"] == match.owner_id
