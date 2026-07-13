from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import config
from app.core.database import get_db
from app.models.match import MatchStatus
from app.routers import match as match_router
from app.schemas.match import MatchInternalEvidenceUpload


class FakeDb:
    def __init__(self):
        self.rollback_count = 0

    def rollback(self):
        self.rollback_count += 1


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_API_KEY", "arena-internal-test-key")
    app = FastAPI()
    app.include_router(match_router.router)
    app.dependency_overrides[get_db] = FakeDb
    return TestClient(app)


def evidence_body(**overrides):
    body = {
        "match_id": 42,
        "telegram_id": 1001,
        "screenshot_file_id": "telegram-photo-id",
    }
    body.update(overrides)
    return body


def test_internal_evidence_requires_internal_key_only(client):
    path = "/matches/internal/evidence"
    assert client.post(path, json=evidence_body()).status_code == 401
    assert (
        client.post(
            path,
            json=evidence_body(),
            headers={"X-Internal-Api-Key": "wrong-key"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            path,
            json=evidence_body(),
            headers={"X-Telegram-Init-Data": "not-internal-auth"},
        ).status_code
        == 401
    )


def test_internal_evidence_delegates_identity_and_slots(monkeypatch):
    captured = {}
    match = SimpleNamespace(id=42, status=MatchStatus.PLAYING)

    def upload(**kwargs):
        captured.update(kwargs)
        return match

    monkeypatch.setattr(match_router.match_crud, "upload_result_screenshot", upload)
    payload = MatchInternalEvidenceUpload.model_validate(
        evidence_body(video_file_id="telegram-video-id")
    )
    result = match_router.upload_internal_match_evidence(
        payload=payload, _=None, db=FakeDb()
    )

    assert result is match
    assert captured["match_id"] == 42
    assert captured["telegram_id"] == 1001
    assert captured["screenshot_file_id"] == "telegram-photo-id"
    assert captured["video_file_id"] == "telegram-video-id"


def test_internal_evidence_wrong_participant_is_forbidden(client, monkeypatch):
    def reject(**_kwargs):
        raise ValueError("Siz bu match ishtirokchisi emassiz")

    monkeypatch.setattr(match_router.match_crud, "upload_result_screenshot", reject)
    response = client.post(
        "/matches/internal/evidence",
        json=evidence_body(telegram_id=9999),
        headers={"X-Internal-Api-Key": "arena-internal-test-key"},
    )
    assert response.status_code == 403
    assert "ishtirokchisi emassiz" in response.json()["detail"]


def test_internal_schema_requires_positive_identity_and_evidence():
    with pytest.raises(ValidationError):
        MatchInternalEvidenceUpload.model_validate(
            {"match_id": 42, "telegram_id": 1001}
        )
    with pytest.raises(ValidationError):
        MatchInternalEvidenceUpload.model_validate(
            evidence_body(telegram_id=0)
        )
    with pytest.raises(ValidationError):
        MatchInternalEvidenceUpload.model_validate(
            evidence_body(match_id=0)
        )


def test_public_evidence_contract_is_unchanged():
    route = next(
        route
        for route in match_router.router.routes
        if route.path == "/matches/{match_id}/screenshot"
    )
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    assert match_router.get_current_telegram_user in dependency_calls
