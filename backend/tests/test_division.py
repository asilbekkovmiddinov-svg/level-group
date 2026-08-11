import hashlib
import hmac
import json
import time
from decimal import Decimal
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import admin_auth, telegram_auth
from app.core.database import Base, get_db
from app.models.arena_v3 import ArenaV3Match, ArenaV3MatchEvent
from app.models.division import (
    DivisionMatch,
    DivisionParticipant,
    DivisionSeason,
    DivisionTicketLedger,
)
from app.models.user import User
from app.models.wall_rush import GameTicketWallet
from app.routers.division import admin_router, router
from app.services.arena_v3 import ArenaV3Service
from app.services.division import DivisionService


def init_data(telegram_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": telegram_id, "first_name": f"User {telegram_id}"},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def headers(telegram_id: int) -> dict[str, str]:
    return {"X-Telegram-Init-Data": init_data(telegram_id)}


def build(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            DivisionSeason.__table__,
            DivisionParticipant.__table__,
            GameTicketWallet.__table__,
            ArenaV3Match.__table__,
            ArenaV3MatchEvent.__table__,
            DivisionMatch.__table__,
            DivisionTicketLedger.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(admin_auth, "ADMIN_TELEGRAM_IDS", frozenset({9001}))
    app = FastAPI()
    app.include_router(router)
    app.include_router(admin_router)

    def dependency():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = dependency
    client = TestClient(app)
    db = sessions()
    db.add_all(
        [
            User(telegram_id=9001, username="admin", first_name="Admin"),
            User(telegram_id=101, username="alpha", first_name="Ali"),
            User(telegram_id=102, username="beta", first_name="Vali"),
        ]
    )
    db.add_all(
        [
            GameTicketWallet(telegram_id=101, tournament_tickets=1),
            GameTicketWallet(telegram_id=102, tournament_tickets=1),
        ]
    )
    db.commit()
    db.close()
    return client, sessions, engine


def season_payload():
    now = datetime.now(timezone.utc)
    return {
        "name": "Global Division S1",
        "registration_opens_at": (now - timedelta(hours=1)).isoformat(),
        "registration_closes_at": (now + timedelta(hours=1)).isoformat(),
        "starts_at": (now + timedelta(hours=2)).isoformat(),
    }


def test_division_admin_creates_fixed_30_day_global_season(monkeypatch):
    client, _sessions, engine = build(monkeypatch)
    try:
        assert client.post("/admin/division/seasons", json=season_payload()).status_code == 401
        assert (
            client.post(
                "/admin/division/seasons",
                json=season_payload(),
                headers=headers(101),
            ).status_code
            == 403
        )

        response = client.post(
            "/admin/division/seasons",
            json=season_payload(),
            headers=headers(9001),
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Global Division S1"
        assert data["status"] == "REGISTRATION"
        assert data["duration_days"] == 30
        assert data["ticket_cost"] == 1
        assert data["points_for_win"] == 3
        assert data["points_for_loss"] == 0
        assert (
            datetime.fromisoformat(data["ends_at"])
            - datetime.fromisoformat(data["starts_at"])
            == timedelta(days=30)
        )

        duplicate = client.post(
            "/admin/division/seasons",
            json=season_payload(),
            headers=headers(9001),
        )
        assert duplicate.status_code == 409
    finally:
        engine.dispose()


def test_application_approval_and_standings_flow(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        season = client.post(
            "/admin/division/seasons",
            json=season_payload(),
            headers=headers(9001),
        ).json()

        first = client.post("/division/apply", headers=headers(101))
        assert first.status_code == 201
        assert first.json()["status"] == "PENDING"
        repeated = client.post("/division/apply", headers=headers(101))
        assert repeated.status_code == 201
        assert repeated.json()["id"] == first.json()["id"]

        second = client.post("/division/apply", headers=headers(102))
        assert second.status_code == 201

        pending = client.get(
            f"/admin/division/seasons/{season['id']}/applications?status=PENDING",
            headers=headers(9001),
        )
        assert pending.status_code == 200
        assert pending.json()["total"] == 2

        for participant in (first.json(), second.json()):
            approved = client.post(
                (
                    f"/admin/division/seasons/{season['id']}/applications/"
                    f"{participant['id']}/decision"
                ),
                json={"decision": "APPROVED"},
                headers=headers(9001),
            )
            assert approved.status_code == 200
            assert approved.json()["status"] == "APPROVED"

        db = sessions()
        alpha = db.get(DivisionParticipant, first.json()["id"])
        beta = db.get(DivisionParticipant, second.json()["id"])
        alpha.matches_played, alpha.wins, alpha.losses = 2, 2, 0
        alpha.points, alpha.goals_for, alpha.goals_against = 6, 5, 1
        beta.matches_played, beta.wins, beta.losses = 2, 1, 1
        beta.points, beta.goals_for, beta.goals_against = 3, 3, 2
        db.commit()
        db.close()

        standings = client.get("/division/standings", headers=headers(101))
        assert standings.status_code == 200
        table = standings.json()
        assert table["total"] == 2
        assert [item["username"] for item in table["items"]] == ["alpha", "beta"]
        assert table["items"][0]["rank"] == 1
        assert table["items"][0]["goal_difference"] == 4

        overview = client.get("/division/me", headers=headers(101))
        assert overview.status_code == 200
        assert overview.json()["participant"]["points"] == 6

        started = client.post(
            f"/admin/division/seasons/{season['id']}/start",
            headers=headers(9001),
        )
        assert started.status_code == 200
        assert started.json()["status"] == "ACTIVE"
        assert client.post("/division/apply", headers=headers(101)).status_code == 409

        finished = client.post(
            f"/admin/division/seasons/{season['id']}/finish",
            headers=headers(9001),
        )
        assert finished.status_code == 200
        assert finished.json()["status"] == "FINISHED"
    finally:
        engine.dispose()



def approve_and_start(client, season_id: int):
    participants = []
    for telegram_id in (101, 102):
        participant = client.post(
            "/division/apply", headers=headers(telegram_id)
        ).json()
        participants.append(participant)
        response = client.post(
            (
                f"/admin/division/seasons/{season_id}/applications/"
                f"{participant['id']}/decision"
            ),
            json={"decision": "APPROVED"},
            headers=headers(9001),
        )
        assert response.status_code == 200
    response = client.post(
        f"/admin/division/seasons/{season_id}/start",
        headers=headers(9001),
    )
    assert response.status_code == 200
    return participants


def test_matchmaking_locks_refunds_and_spends_tournament_tickets(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        season = client.post(
            "/admin/division/seasons",
            json=season_payload(),
            headers=headers(9001),
        ).json()
        approve_and_start(client, season["id"])

        waiting = client.post(
            "/division/matchmaking/join", headers=headers(101)
        )
        assert waiting.status_code == 200
        assert waiting.json()["status"] == "WAITING"
        repeated = client.post(
            "/division/matchmaking/join", headers=headers(101)
        )
        assert repeated.json()["id"] == waiting.json()["id"]

        db = sessions()
        wallet = db.get(GameTicketWallet, 101)
        assert wallet.tournament_tickets == 0
        assert wallet.locked_tournament_tickets == 1
        db.close()

        cancelled = client.post(
            (
                f"/division/matches/{waiting.json()['id']}/"
                "cancel-waiting"
            ),
            headers=headers(101),
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"
        assert cancelled.json()["player_a_ticket_state"] == "REFUNDED"

        first = client.post(
            "/division/matchmaking/join", headers=headers(101)
        ).json()
        matched = client.post(
            "/division/matchmaking/join", headers=headers(102)
        )
        assert matched.status_code == 200
        assert matched.json()["id"] == first["id"]
        assert matched.json()["status"] == "MATCHED"
        assert matched.json()["player_a_ticket_state"] == "LOCKED"
        assert matched.json()["player_b_ticket_state"] == "LOCKED"

        db = sessions()
        for telegram_id in (101, 102):
            wallet = db.get(GameTicketWallet, telegram_id)
            assert wallet.tournament_tickets == 0
            assert wallet.locked_tournament_tickets == 1
        db.close()

        db = sessions()
        division_match = db.get(DivisionMatch, matched.json()["id"])
        arena_match = db.get(ArenaV3Match, division_match.arena_match_id)
        assert arena_match.match_type == "DIVISION"
        assert arena_match.status.value == "READY"
        assert arena_match.stake_efc == Decimal("0.00")
        assert arena_match.total_pool_efc == Decimal("0.00")
        arena_service = ArenaV3Service(db)
        arena_service.ready(
            match_id=arena_match.id, player_id=101
        )
        arena_service.ready(
            match_id=arena_match.id, player_id=102
        )
        started = arena_service.submit_room_code(
            match_id=arena_match.id,
            owner_id=101,
            payload=SimpleNamespace(room_code="ABC123"),
        )
        assert started.status.value == "PLAYING"
        db.close()

        db = sessions()
        activated = db.get(DivisionMatch, matched.json()["id"])
        assert activated.status.value == "ACTIVE"
        for telegram_id in (101, 102):
            wallet = db.get(GameTicketWallet, telegram_id)
            assert wallet.tournament_tickets == 0
            assert wallet.locked_tournament_tickets == 0
        operations = [
            row.operation
            for row in db.query(DivisionTicketLedger)
            .filter(
                DivisionTicketLedger.match_id == matched.json()["id"]
            )
            .order_by(DivisionTicketLedger.created_at)
            .all()
        ]
        assert operations.count("LOCK") == 2
        assert operations.count("SPEND") == 2
        db.close()
    finally:
        engine.dispose()


def test_matched_cancel_before_start_refunds_both_players(monkeypatch):
    client, sessions, engine = build(monkeypatch)
    try:
        season = client.post(
            "/admin/division/seasons",
            json=season_payload(),
            headers=headers(9001),
        ).json()
        approve_and_start(client, season["id"])
        client.post("/division/matchmaking/join", headers=headers(101))
        matched = client.post(
            "/division/matchmaking/join", headers=headers(102)
        ).json()

        db = sessions()
        cancelled = DivisionService(db).cancel_before_start(
            matched["id"], "READY_TIMEOUT"
        )
        assert cancelled.status.value == "CANCELLED"
        db.close()

        db = sessions()
        for telegram_id in (101, 102):
            wallet = db.get(GameTicketWallet, telegram_id)
            assert wallet.tournament_tickets == 1
            assert wallet.locked_tournament_tickets == 0
        assert (
            db.query(DivisionTicketLedger)
            .filter(
                DivisionTicketLedger.match_id == matched["id"],
                DivisionTicketLedger.operation == "REFUND",
            )
            .count()
            == 2
        )
        db.close()
    finally:
        engine.dispose()
