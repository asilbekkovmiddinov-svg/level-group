import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import telegram_auth
from app.core.database import Base, get_db
from app.models.match import Match, MatchGameType, MatchStats, MatchStatus
from app.models.user import User
from app.routers import arena_v4, match as match_router
from app.services import arena_v4 as arena_service


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def make_init_data(telegram_id=1001):
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Ali"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def headers(telegram_id=1001):
    return {"X-Telegram-Init-Data": make_init_data(telegram_id)}


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, Match.__table__, MatchStats.__table__],
    )
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            User(telegram_id=1001, first_name="Ali", last_seen_at=NOW),
            User(telegram_id=2002, first_name="Vali", last_seen_at=NOW),
            User(telegram_id=3003, first_name="Sami", last_seen_at=NOW - timedelta(hours=1)),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(arena_service, "utc_now", lambda: NOW)
    app = FastAPI()
    app.include_router(match_router.router)
    app.include_router(arena_v4.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def create_match(
    db,
    *,
    creator=1001,
    opponent=None,
    stake=100,
    status=MatchStatus.WAITING_PLAYER,
    created_at=None,
    resolved_at=None,
    winner=None,
    loser=None,
):
    stake_value = Decimal(stake)
    match = Match(
        creator_telegram_id=creator,
        opponent_telegram_id=opponent,
        game_type=MatchGameType.EFOOTBALL,
        efc_amount=stake_value,
        total_pool=stake_value * 2,
        commission_amount=stake_value / 10,
        winner_reward=stake_value * Decimal("1.9"),
        status=status,
        scheduled_at=NOW + timedelta(minutes=10),
        created_at=created_at or NOW,
        updated_at=resolved_at or NOW,
        resolved_at=resolved_at,
        winner_telegram_id=winner,
        loser_telegram_id=loser,
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


def test_dashboard_returns_all_stakes_with_backend_aggregates(client, db):
    create_match(db, creator=1001, stake=100, created_at=NOW - timedelta(seconds=120))
    create_match(db, creator=2002, stake=100, created_at=NOW - timedelta(seconds=60))
    create_match(db, creator=3003, stake=500, created_at=NOW - timedelta(seconds=30))

    response = client.get("/arena/dashboard", headers=headers())

    assert response.status_code == 200
    stakes = {item["stake"]: item for item in response.json()["stakes"]}
    assert list(stakes) == [100, 500, 1000, 5000, 10000]
    assert stakes[100] == {
        "stake": 100,
        "online_players": 2,
        "open_rooms": 2,
        "average_wait_time": 90,
    }
    assert stakes[500]["online_players"] == 0


def test_match_history_is_authenticated_user_specific_and_backward_compatible(client, db):
    won = create_match(
        db,
        opponent=2002,
        status=MatchStatus.COMPLETED,
        resolved_at=NOW,
        winner=1001,
        loser=2002,
    )

    response = client.get("/matches/me", headers=headers(1001))

    assert response.status_code == 200
    item = response.json()["matches"][0]
    assert item["id"] == won.id
    assert item["game"] == "EFOOTBALL"
    assert item["stake"] == "100.00"
    assert item["result"] == "WIN"
    assert item["reward"] == "190.00"
    assert item["completed_at"] is not None
    assert item["game_type"] == "EFOOTBALL"
    assert item["efc_amount"] == "100.00"

    lost = client.get("/matches/me", headers=headers(2002)).json()["matches"][0]
    assert lost["result"] == "LOSE"
    assert lost["reward"] == "0"


def test_profile_returns_authoritative_stats_and_zero_defaults(client, db):
    db.add(
        MatchStats(
            telegram_id=1001,
            total_matches=10,
            wins=7,
            losses=3,
            win_rate=Decimal("70"),
            total_efc_won=Decimal("950"),
            win_streak=2,
            best_win_streak=5,
        )
    )
    db.commit()

    profile = client.get("/arena/profile", headers=headers(1001))
    assert profile.status_code == 200
    assert profile.json() == {
        "total_matches": 10,
        "wins": 7,
        "losses": 3,
        "win_rate": "70.00",
        "total_efc_won": "950.00",
        "current_streak": 2,
        "best_streak": 5,
    }
    assert client.get("/arena/profile", headers=headers(2002)).json()["total_matches"] == 0


def test_leaderboard_applies_period_ranking_and_top_100(client, db):
    create_match(
        db,
        opponent=2002,
        status=MatchStatus.COMPLETED,
        resolved_at=NOW - timedelta(days=2),
        winner=1001,
        loser=2002,
    )
    create_match(
        db,
        creator=3003,
        opponent=1001,
        status=MatchStatus.COMPLETED,
        resolved_at=NOW - timedelta(days=40),
        winner=3003,
        loser=1001,
    )

    weekly = client.get("/arena/leaderboard?period=weekly&limit=100", headers=headers())
    all_time = client.get("/arena/leaderboard?period=all&limit=100", headers=headers())

    assert weekly.status_code == 200
    assert weekly.json()["period"] == "weekly"
    assert [user["display_name"] for user in weekly.json()["users"]] == ["Ali", "Vali"]
    assert weekly.json()["users"][0]["rank"] == 1
    assert weekly.json()["users"][0]["win_rate"] == "100"
    assert len(all_time.json()["users"]) == 3
    assert client.get("/arena/leaderboard?period=yearly", headers=headers()).status_code == 422


def test_all_v4_endpoints_require_verified_init_data(client):
    assert client.get("/arena/dashboard").status_code == 401
    assert client.get("/arena/profile").status_code == 401
    assert client.get("/arena/leaderboard").status_code == 401
    assert client.get("/matches/me").status_code == 401


def test_dashboard_and_leaderboard_use_bounded_query_counts(db):
    create_match(db, creator=1001, opponent=2002, stake=100)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        arena_service.get_dashboard(db)
        dashboard_queries = len(statements)
        statements.clear()
        arena_service.get_leaderboard(db, period="all", limit=100)
        leaderboard_queries = len(statements)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)

    assert dashboard_queries <= 2
    assert leaderboard_queries == 1
