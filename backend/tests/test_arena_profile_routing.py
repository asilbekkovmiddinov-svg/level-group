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
from app.core.database import Base, get_db
from app.core.telegram_auth import get_current_telegram_user
from app.models.arena_v3 import ArenaV3Stats
from app.models.match import MatchStats
from app.models.user import User
from app.routers.arena_v3 import router as arena_v3_router
from app.routers.arena_v4 import get_arena_profile, router as arena_profile_router


@pytest.fixture
def profile_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    db.add_all(
        [
            User(telegram_id=1001, first_name="V2"),
            User(telegram_id=2002, first_name="V3"),
            MatchStats(
                telegram_id=1001,
                total_matches=10,
                wins=7,
                losses=3,
                win_rate=Decimal("70"),
                total_efc_won=Decimal("950"),
                win_streak=2,
                best_win_streak=5,
            ),
            ArenaV3Stats(
                player_id=2002,
                total_matches=8,
                wins=5,
                losses=2,
                draws=1,
                goals_for=15,
                goals_against=9,
                win_rate=Decimal("62.50"),
                current_streak=3,
                best_streak=4,
                total_efc_won=Decimal("600"),
                total_efc_lost=Decimal("200"),
            ),
        ]
    )
    db.commit()

    current_player = {"telegram_id": 1001}
    application = FastAPI()
    application.include_router(arena_profile_router)
    application.include_router(arena_v3_router)
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_current_telegram_user] = (
        lambda: SimpleNamespace(telegram_id=current_player["telegram_id"])
    )
    monkeypatch.setattr(config, "ARENA_V3_ENABLED", False)
    monkeypatch.setattr(config, "ARENA_V3_ALLOWED_TELEGRAM_IDS", frozenset({2002}))
    try:
        yield TestClient(application), current_player
    finally:
        db.close()


def test_arena_profile_has_one_deterministic_route(profile_client):
    routes = [
        route
        for route in [*arena_profile_router.routes, *arena_v3_router.routes]
        if getattr(route, "path", None) == "/arena/profile"
        and "GET" in getattr(route, "methods", set())
    ]
    assert len(routes) == 1
    assert routes[0].endpoint is get_arena_profile


def test_arena_profile_preserves_v2_for_non_v3_users(profile_client):
    client, current_player = profile_client
    current_player["telegram_id"] = 1001

    response = client.get("/arena/profile")

    assert response.status_code == 200
    assert response.json() == {
        "total_matches": 10,
        "wins": 7,
        "losses": 3,
        "win_rate": "70.00",
        "total_efc_won": "950.00",
        "current_streak": 2,
        "best_streak": 5,
    }


def test_arena_profile_returns_v3_contract_for_allowlisted_user(profile_client):
    client, current_player = profile_client
    current_player["telegram_id"] = 2002

    response = client.get("/arena/profile")

    assert response.status_code == 200
    assert response.json() == {
        "player_id": 2002,
        "total_matches": 8,
        "wins": 5,
        "losses": 2,
        "draws": 1,
        "goals_for": 15,
        "goals_against": 9,
        "win_rate": "62.50",
        "current_streak": 3,
        "best_streak": 4,
        "total_efc_won": "600.00",
        "total_efc_lost": "200.00",
    }
