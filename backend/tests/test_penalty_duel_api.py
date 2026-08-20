import hashlib
import hmac
import json
import time
from datetime import datetime
from urllib.parse import quote, urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import telegram_auth
from app.routers import penalty_duel as penalty_duel_router_module
from app.core.database import Base, get_db
from app.models.penalty_duel import PenaltyDuelMatch, PenaltyDuelMode, PenaltyDuelRound, PenaltyDuelStatus, PenaltyDuelSubmission
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
        rating_payload = rating.json()
        assert rating_payload["mode"] == "FREE"
        assert rating_payload["period"] == "WEEKLY"
        assert rating_payload["rows"] == []
        assert datetime.fromisoformat(rating_payload["week_end_at"]) > datetime.fromisoformat(
            rating_payload["week_start_at"]
        )
    finally:
        engine.dispose()


def test_realtime_refresh_is_subsecond():
    assert PENALTY_WEBSOCKET_REFRESH_SECONDS == 0.25


def test_finished_match_can_be_recovered_by_id_after_active_query_is_empty(monkeypatch):
    client, engine = build(monkeypatch)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(penalty_duel_router_module, "SessionLocal", sessions)
    db = sessions()
    match = PenaltyDuelMatch(
        id="finished-penalty-match",
        mode=PenaltyDuelMode.FREE,
        status=PenaltyDuelStatus.FINISHED,
        player_one_id=101,
        player_two_id=202,
        round_number=10,
        player_one_score=4,
        player_two_score=3,
        winner_id=101,
        version=12,
    )
    db.add(match)
    db.commit()
    db.close()
    try:
        assert client.get("/penalty-duel/matches/active", headers=headers(101)).json() is None
        recovered = client.get(
            "/penalty-duel/matches/finished-penalty-match",
            headers=headers(101),
        )
        assert recovered.status_code == 200
        assert recovered.json()["status"] == "FINISHED"
        assert recovered.json()["winner_id"] == 101
        assert client.get(
            "/penalty-duel/matches/finished-penalty-match",
            headers=headers(303),
        ).status_code == 404

        init_data = quote(make_init_data(101), safe="")
        with client.websocket_connect(
            f"/penalty-duel/ws?init_data={init_data}&match_id=finished-penalty-match"
        ) as websocket:
            message = websocket.receive_json()
            assert message["match"]["status"] == "FINISHED"
            assert message["match"]["id"] == "finished-penalty-match"
    finally:
        engine.dispose()


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

        # Shot 1: player one attacks, player two keeps. Each submits one direction only.
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
        assert payload["history"][0]["your_kick"] == "top-right"
        assert payload["history"][0]["opponent_keeper"] == "top-left"
        assert payload["history"][0]["you_goal"] is True
        assert payload["your_score"] == 1
        assert payload["opponent_score"] == 0
    finally:
        engine.dispose()
