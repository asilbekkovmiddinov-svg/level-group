import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import admin_auth, telegram_auth
from app.core.database import Base, get_db
from app.models.promotion import Promotion, PromotionEvent
from app.routers.promotion_analytics import admin_router, public_router
from app.services.promotion_analytics import aggregate, percentage


def init_data(telegram_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Analytics User"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def sessions_and_promotions():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Promotion.__table__, PromotionEvent.__table__])
    sessions = sessionmaker(bind=engine)
    db = sessions()
    db.add_all([
        Promotion(id=1, title="Alpha", status="ACTIVE", button_action="NONE", priority=10),
        Promotion(id=2, title="Beta", status="ACTIVE", button_action="NONE", priority=20),
    ])
    db.commit()
    return sessions, db


def add_event(db, promotion_id, telegram_id, event_type, occurred_at):
    db.add(PromotionEvent(
        promotion_id=promotion_id,
        telegram_id=telegram_id,
        event_type=event_type,
        occurred_at=occurred_at,
    ))


def test_analytics_aggregation_ctr_conversion_and_unique_counting():
    _, db = sessions_and_promotions()
    now = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
    for promotion_id, telegram_id, event_type in [
        (1, 101, "VIEW"), (1, 101, "VIEW"), (1, 102, "VIEW"), (1, 101, "CLICK"),
        (2, 103, "VIEW"), (2, 103, "CLICK"), (2, 103, "CLICK"),
    ]:
        add_event(db, promotion_id, telegram_id, event_type, now - timedelta(hours=1))
    db.commit()
    report = aggregate(db, "TODAY", now)
    alpha = next(item for item in report["promotions"] if item["promotion_id"] == 1)
    assert alpha["views"] == 3
    assert alpha["unique_views"] == 2
    assert alpha["clicks"] == 1
    assert alpha["unique_clicks"] == 1
    assert alpha["unique_users"] == 2
    assert alpha["ctr"] == 33.33
    assert alpha["conversion_rate"] == 50.0
    assert report["summary"] == {
        "views": 4, "unique_views": 3, "clicks": 3, "unique_clicks": 2,
        "unique_users": 3, "ctr": 75.0, "conversion_rate": 66.67,
    }
    assert report["most_clicked"][0]["promotion_id"] == 2
    assert report["highest_ctr"][0]["promotion_id"] == 2
    assert percentage(0, 0) == 0.0


def test_period_filters_and_daily_chart_data():
    _, db = sessions_and_promotions()
    now = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
    add_event(db, 1, 101, "VIEW", now - timedelta(hours=1))
    add_event(db, 1, 101, "CLICK", now - timedelta(days=8))
    add_event(db, 2, 102, "VIEW", now - timedelta(days=31))
    db.commit()
    assert aggregate(db, "TODAY", now)["summary"]["views"] == 1
    seven = aggregate(db, "7D", now)
    assert seven["summary"]["clicks"] == 0
    assert len(seven["daily"]) == 7
    thirty = aggregate(db, "30D", now)
    assert thirty["summary"]["clicks"] == 1
    assert len(thirty["daily"]) == 30
    all_time = aggregate(db, "ALL", now)
    assert all_time["summary"]["views"] == 2
    assert all_time["summary"]["clicks"] == 1
    assert all(row.keys() == {"date", "views", "clicks", "ctr"} for row in all_time["daily"])


def test_tracking_admin_security_and_csv_export(monkeypatch):
    sessions, db = sessions_and_promotions()
    db.close()
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(admin_auth, "ADMIN_TELEGRAM_IDS", frozenset({9001}))
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)

    def dependency():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = dependency
    client = TestClient(app)
    user_headers = {"X-Telegram-Init-Data": init_data(501)}
    assert client.post("/promotions/1/view", headers=user_headers).status_code == 204
    assert client.post("/promotions/1/click", headers=user_headers).status_code == 204
    assert client.get("/admin/promotions/analytics?period=7D").status_code == 401
    assert client.get(
        "/admin/promotions/analytics?period=7D",
        headers={"X-Telegram-Init-Data": init_data(7777)},
    ).status_code == 403
    admin_headers = {"X-Telegram-Init-Data": init_data(9001)}
    analytics = client.get("/admin/promotions/analytics?period=7D", headers=admin_headers)
    assert analytics.status_code == 200
    assert analytics.json()["summary"]["ctr"] == 100.0
    exported = client.get("/admin/promotions/analytics/export?period=7D", headers=admin_headers)
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "promotion_id,title,status,priority,views" in exported.text
    assert "1,Alpha,ACTIVE,10,1" in exported.text
    stored = sessions().get(Promotion, 1)
    assert stored.view_count == 1
    assert stored.click_count == 1
    assert stored.last_viewed_at is not None
    assert stored.last_clicked_at is not None
