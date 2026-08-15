from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.admin_auth import require_promotions_admin
from app.core.database import Base, get_db
from app.routers.arena_v3 import admin_router, require_arena_v3_access, router


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    application = FastAPI()
    application.include_router(router)
    application.include_router(admin_router)
    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[require_arena_v3_access] = lambda: SimpleNamespace(
        telegram_id=1001
    )
    application.dependency_overrides[require_promotions_admin] = lambda: SimpleNamespace(
        telegram_id=9001
    )
    return TestClient(application)


def test_admin_can_write_weekly_and_monthly_ranking_prizes():
    client = _client()

    weekly = client.put(
        "/admin/arena/ranking-prizes/weekly",
        json={"prize_text": "  1-o‘rin: 100 000 so‘m  "},
    )
    monthly = client.put(
        "/admin/arena/ranking-prizes/monthly",
        json={"prize_text": "1-o‘rin: eFootball akkaunt"},
    )

    assert weekly.status_code == 200
    assert weekly.json()["prize_text"] == "1-o‘rin: 100 000 so‘m"
    assert monthly.status_code == 200
    assert client.get("/admin/arena/ranking-prizes").json() == [
        {
            "period": "weekly",
            "prize_text": "1-o‘rin: 100 000 so‘m",
            "updated_at": weekly.json()["updated_at"],
        },
        {
            "period": "monthly",
            "prize_text": "1-o‘rin: eFootball akkaunt",
            "updated_at": monthly.json()["updated_at"],
        },
    ]


def test_public_ranking_contains_period_prize_and_all_time_has_none():
    client = _client()
    client.put(
        "/admin/arena/ranking-prizes/weekly",
        json={"prize_text": "Top 3 uchun Tournament Ticket"},
    )

    weekly = client.get("/arena/ranking?period=weekly")
    all_time = client.get("/arena/ranking?period=all")

    assert weekly.status_code == 200
    assert weekly.json()["prize_text"] == "Top 3 uchun Tournament Ticket"
    assert weekly.json()["players"] == []
    assert all_time.status_code == 200
    assert all_time.json()["prize_text"] is None


def test_admin_can_clear_prize_and_invalid_period_is_rejected():
    client = _client()
    client.put(
        "/admin/arena/ranking-prizes/weekly",
        json={"prize_text": "Mukofot"},
    )

    cleared = client.put(
        "/admin/arena/ranking-prizes/weekly",
        json={"prize_text": "   "},
    )

    assert cleared.status_code == 200
    assert cleared.json()["prize_text"] is None
    assert client.put(
        "/admin/arena/ranking-prizes/all",
        json={"prize_text": "No"},
    ).status_code == 422
