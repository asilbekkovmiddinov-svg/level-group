import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import telegram_auth
from app.core.database import Base, get_db
from app.models.penalty_duel import PenaltyDuelMatch, PenaltyDuelRound, PenaltyDuelSubmission
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.routers.penalty_duel import router
from app.routers.penalty_duel import PENALTY_WEBSOCKET_REFRESH_SECONDS


def make_init_data(telegram_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": telegram_id, "first_name": f"Player {telegram_id}"},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"penalty-test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def headers(telegram_id: int) -> dict[str, str]:
    return {"X-Telegram-Init-Data": make_init_data(telegram_id)}


def build(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__,
        PenaltyDuelMatch.__table__,
        PenaltyDuelSubmission.__table__,
        PenaltyDuelRound.__table__,
        GameTicketWallet.__table__,
        GameTicketLedger.__table__,
    ])
    sessions = sessionmaker(bind=engine)
    db = sessions()
    db.add_all([
        User(telegram_id=101, first_name="Asil"),
        User(telegram_id=202, first_name="Jocker"),
    ])
    db.commit()
    db.close()

    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "penalty-test-token")
    app = FastAPI()
    app.include_router(router)

    def dependency():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = dependency
    return TestClient(app), engine


def test_public_penalty_endpoints_require_verified_telegram_identity(monkeypatch):
    client, engine = build(monkeypatch)
    try:
        assert client.get("/penalty-duel/matches/active").status_code == 401
        assert client.post(
            "/penalty-duel/matchmaking/join",
            json={"mode": "FREE", "telegram_id": 999},
            headers=headers(101),
        ).status_code == 422

        joined = client.post(
            "/penalty-duel/matchmaking/join",
            json={"mode": "FREE"},
            headers=headers(101),
        )
        assert joined.status_code == 200
        assert joined.json()["you"]["telegram_id"] == 101
        assert joined.json()["status"] == "WAITING"
        assert client.get("/penalty-duel/leaderboard?mode=FREE").status_code == 401
        rating = client.get(
            "/penalty-duel/leaderboard?mode=FREE&limit=20",
            headers=headers(101),
        )
        assert rating.status_code == 200
        assert rating.json() == {"mode": "FREE", "rows": []}
    finally:
        engine.dispose()


def test_realtime_refresh_is_subsecond():
    assert PENALTY_WEBSOCKET_REFRESH_SECONDS == 0.25


def test_http_flow_hides_choices_and_returns_authoritative_score(monkeypatch):
    client, engine = build(monkeypatch)
    try:
        waiting = client.post(
            "/penalty-duel/matchmaking/join",
            json={"mode": "FREE"},
            headers=headers(101),
        ).json()
        active = client.post(
            "/penalty-duel/matchmaking/join",
            json={"mode": "FREE"},
            headers=headers(202),
        ).json()
        assert active["id"] == waiting["id"]
        assert active["status"] == "ACTIVE"

        # Round 1: player 202 is the shooter and submits only the shot direction.
        first = client.post(
            f"/penalty-duel/matches/{active['id']}/choices",
            json={
                "direction": "top-left",
                "idempotency_key": "api-player-two-round-one",
            },
            headers=headers(202),
        )
        assert first.status_code == 200

        opponent_view = client.get(
            "/penalty-duel/matches/active",
            headers=headers(101),
        ).json()
        assert opponent_view["opponent_submitted"] is True
        assert opponent_view["history"] == []
        assert "kick_direction" not in opponent_view

        # Player 101 is the keeper and submits only the save direction.
        resolved = client.post(
            f"/penalty-duel/matches/{active['id']}/choices",
            json={
                "direction": "top-right",
                "idempotency_key": "api-player-one-round-one",
            },
            headers=headers(101),
        )
        assert resolved.status_code == 200
        payload = resolved.json()
        assert payload["round_number"] == 2
        assert len(payload["history"]) == 1
        assert payload["history"][0]["shooter_direction"] == "top-left"
        assert payload["history"][0]["keeper_direction"] == "top-right"
        assert payload["your_score"] + payload["opponent_score"] == 1
    finally:
        engine.dispose()
