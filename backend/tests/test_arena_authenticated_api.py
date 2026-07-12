import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.database import get_db
from app.core import telegram_auth
from app.core.telegram_auth import TelegramUser, verify_init_data
from app.models.match import MatchGameType, MatchStatus
from app.routers import match as match_router
from app.schemas.match import MatchAccept, MatchCreate, MatchReady, MatchRoomCodeCreate


FIXED_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
FUTURE_MATCH_TIME = datetime(2030, 1, 1, 12, 0)


def make_init_data(telegram_id=1001, auth_date=None):
    values = {
        "auth_date": str(auth_date or int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Ali"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def fake_match(status=MatchStatus.WAITING_PLAYER):
    return SimpleNamespace(
        id=42,
        creator_telegram_id=1001,
        opponent_telegram_id=2002,
        game_type=MatchGameType.EFOOTBALL,
        creator_display_name="Ali",
        opponent_display_name="Vali",
        efc_amount=100,
        total_pool=200,
        commission_amount=10,
        winner_reward=190,
        status=status,
        scheduled_at=FUTURE_MATCH_TIME,
        ready_window_started_at=None,
        ready_deadline_at=None,
        creator_ready=False,
        opponent_ready=False,
        room_code="private-room",
        result_type=None,
        resolved_at=None,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    app = FastAPI()
    app.include_router(match_router.router)
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


def headers(telegram_id=1001):
    return {"X-Telegram-Init-Data": make_init_data(telegram_id)}


def test_init_data_rejects_missing_and_expired(monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    with pytest.raises(HTTPException) as missing:
        telegram_auth.get_current_telegram_user()
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as expired:
        verify_init_data(make_init_data(auth_date=int(time.time()) - 90000))
    assert expired.value.status_code == 401


def test_create_schema_rejects_identity_fields():
    with pytest.raises(ValidationError):
        MatchCreate.model_validate(
            {
                "stake_efc": 100,
                "scheduled_at": FIXED_NOW.isoformat(),
                "rules_accepted": True,
                "creator_telegram_id": 9999,
            }
        )

    with pytest.raises(ValidationError):
        MatchAccept.model_validate({"rules_accepted": True, "telegram_id": 9999})

    with pytest.raises(ValidationError):
        MatchReady.model_validate({"user_id": 9999})

    with pytest.raises(ValidationError):
        MatchRoomCodeCreate.model_validate({"room_code": "abc", "telegram_id": 9999})


def test_create_uses_verified_identity_and_requires_rules(client, monkeypatch):
    captured = {}

    def create_match(**kwargs):
        captured.update(kwargs)
        return fake_match()

    monkeypatch.setattr(match_router.match_crud, "create_match", create_match)
    body = {
        "game_type": "EFOOTBALL",
        "stake_efc": 100,
        "scheduled_at": FIXED_NOW.isoformat(),
        "rules_accepted": True,
    }
    response = client.post("/matches/", json=body, headers=headers(1001))

    assert response.status_code == 200
    assert captured["creator_telegram_id"] == 1001
    assert captured["rules_accepted"] is True
    assert "creator_telegram_id" not in response.json()

    body["rules_accepted"] = False
    assert client.post("/matches/", json=body, headers=headers()).status_code == 400
    body["rules_accepted"] = True
    body["creator_telegram_id"] = 1001
    assert client.post("/matches/", json=body, headers=headers()).status_code == 422


def test_user_endpoints_require_auth_and_detail_hides_private_fields(client, monkeypatch):
    match = fake_match(status=MatchStatus.PLAYING)
    monkeypatch.setattr(match_router.match_crud, "get_match", lambda **_: match)

    assert client.get("/matches/42").status_code == 401

    outsider = client.get("/matches/42", headers=headers(9999))
    assert outsider.status_code == 200
    outsider_payload = outsider.json()
    assert outsider_payload["room_code"] is None
    for field in ("creator_telegram_id", "opponent_telegram_id", "creator_username", "room_code_created_by"):
        assert field not in outsider_payload

    participant = client.get("/matches/42", headers=headers(1001))
    assert participant.status_code == 200
    assert participant.json()["room_code"] == "private-room"


def test_join_ready_and_cancel_use_verified_participant_identity(client, monkeypatch):
    captured = {}
    match = fake_match()

    def accept_match(**kwargs):
        captured.update(kwargs)
        return match

    monkeypatch.setattr(match_router.match_crud, "accept_match", accept_match)
    join = client.post("/matches/42/accept", json={"rules_accepted": True}, headers=headers(2002))
    assert join.status_code == 200
    assert captured["opponent_telegram_id"] == 2002

    monkeypatch.setattr(
        match_router.match_crud,
        "accept_match",
        lambda **_: (_ for _ in ()).throw(ValueError("O‘zingiz yaratgan matchni qabul qila olmaysiz")),
    )
    assert client.post("/matches/42/accept", json={"rules_accepted": True}, headers=headers(1001)).status_code == 409

    monkeypatch.setattr(match_router.match_crud, "set_player_ready", lambda **kwargs: match)
    assert client.post("/matches/42/ready", json={}, headers=headers(1001)).status_code == 200

    monkeypatch.setattr(
        match_router.match_crud,
        "set_player_ready",
        lambda **_: (_ for _ in ()).throw(ValueError("Siz bu match ishtirokchisi emassiz")),
    )
    assert client.post("/matches/42/ready", json={}, headers=headers(9999)).status_code == 403

    monkeypatch.setattr(match_router.match_crud, "get_match", lambda **_: match)
    assert client.post(
        "/matches/42/cancel",
        json={"cancel_reason": "Test"},
        headers=headers(9999),
    ).status_code == 403

    monkeypatch.setattr(match_router.match_crud, "cancel_match", lambda **_: match)
    assert client.post(
        "/matches/42/cancel",
        json={"cancel_reason": "Test"},
        headers=headers(1001),
    ).status_code == 200


def test_rules_acceptance_timestamps_are_written_by_service(monkeypatch):
    # This contract is exercised without wallet mutation by replacing the
    # lock helper and using a minimal commit-capable session.
    from app.crud import match as match_crud

    class Session:
        def add(self, value):
            self.value = value

        def commit(self):
            return None

        def refresh(self, value):
            return None

    monkeypatch.setattr(match_crud, "_lock_efc", lambda **_: None)
    created = match_crud.create_match(
        Session(),
        creator_telegram_id=1001,
        efc_amount=100,
        scheduled_at=datetime(2030, 1, 1),
        game_type=MatchGameType.EFOOTBALL,
        rules_accepted=True,
    )
    assert created.creator_rules_accepted_at is not None
    assert created.creator_rules_accepted_at.tzinfo is not None


def test_join_rules_timestamp_is_written_by_service(monkeypatch):
    from app.crud import match as match_crud

    match = fake_match()

    class Session:
        def commit(self):
            return None

        def refresh(self, value):
            return None

    monkeypatch.setattr(match_crud, "get_match", lambda *_: match)
    monkeypatch.setattr(match_crud, "_lock_efc", lambda **_: None)

    updated = match_crud.accept_match(
        Session(),
        match_id=42,
        opponent_telegram_id=2002,
        rules_accepted=True,
    )

    assert updated.opponent_rules_accepted_at is not None
    assert updated.opponent_rules_accepted_at.tzinfo is not None
