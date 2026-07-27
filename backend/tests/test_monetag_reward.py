import hashlib
import hmac
import json
import time
from datetime import datetime
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import telegram_auth
from app.core.database import Base, get_db
from app.crud import wheel
from app.models.user import User
from app.models.wheel import AdsgramRewardSession, MonetagRewardEvent, WheelDailyLimit
from app.routers import monetag_ads
from app.services import monetag_reward


NOW = datetime(2030, 1, 2, 12, 0)
YMID = "11111111-2222-4333-8444-555555555555"


def auth_headers(telegram_id: int) -> dict[str, str]:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Monetag User"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(values)}


@pytest.fixture
def db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            WheelDailyLimit.__table__,
            AdsgramRewardSession.__table__,
            MonetagRewardEvent.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    session.add(User(telegram_id=1001, first_name="Monetag User"))
    session.commit()
    monkeypatch.setattr(monetag_reward, "utc_now", lambda: NOW)
    monkeypatch.setattr(wheel, "get_now", lambda: NOW)
    monkeypatch.setattr(wheel, "get_today", lambda: NOW.date())
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(monetag_ads, "MONETAG_POSTBACK_SECRET", "postback-secret")
    app = FastAPI()
    app.include_router(monetag_ads.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def create_session(client, ymid=YMID):
    return client.post(
        "/api/ads/monetag/session",
        json={"ymid": ymid},
        headers=auth_headers(1001),
    )


def postback(client, **overrides):
    params = {
        "token": "postback-secret",
        "ymid": YMID,
        "telegram_id": 1001,
        "event": "impression",
        "value": "valued",
        "zone": "11422269",
        "sub": "wheel",
        "price": "0.0012",
        "source": "wheel_reward",
        **overrides,
    }
    return client.get("/api/ads/monetag/postback", params=params)


def postback_with_macro_names(client, **overrides):
    params = {
        "token": "postback-secret",
        "ymid": YMID,
        "telegram_id": 1001,
        "event_type": "impression",
        "reward_event_type": "valued",
        "zone_id": "11422269",
        "sub_zone_id": "wheel",
        "estimated_price": "0.0012",
        "request_var": "wheel_reward",
        **overrides,
    }
    return client.get("/api/ads/monetag/postback", params=params)


def test_legacy_parameter_names_claim_reward(client, db):
    assert create_session(client).status_code == 200
    response = postback(client)
    assert response.status_code == 200
    assert response.json()["rewarded"] is True
    assert db.query(WheelDailyLimit).filter_by(telegram_id=1001).one().rewarded_ad_spins == 1


def test_monetag_macro_parameter_names_claim_reward(client, db):
    assert create_session(client).status_code == 200
    response = postback_with_macro_names(client)
    assert response.status_code == 200
    assert response.json() == {"success": True, "rewarded": True, "status": "CLAIMED"}
    event = db.query(MonetagRewardEvent).filter_by(ymid=YMID).one()
    assert event.zone_id == "11422269"
    assert event.sub_zone_id == "wheel"
    assert event.source == "wheel_reward"


def test_legacy_names_take_precedence_in_mixed_postback(client, db):
    assert create_session(client).status_code == 200
    response = postback(
        client,
        event_type="click",
        reward_event_type="non_valued",
        zone_id="wrong-zone",
        sub_zone_id="wrong-sub",
        estimated_price="9.99",
        request_var="wrong-source",
    )
    assert response.status_code == 200
    assert response.json()["rewarded"] is True
    event = db.query(MonetagRewardEvent).filter_by(ymid=YMID).one()
    assert event.event == "impression"
    assert event.reward_type == "valued"
    assert event.zone_id == "11422269"
    assert event.sub_zone_id == "wheel"
    assert str(event.estimated_price) == "0.00120000"
    assert event.source == "wheel_reward"


def test_postback_requires_constant_time_secret_and_pending_ymid(client, db):
    assert create_session(client).status_code == 200
    assert postback(client, token="wrong").status_code == 401
    assert postback(client, token="").status_code == 401

    response = postback(client)
    assert response.status_code == 200
    assert response.json() == {"success": True, "rewarded": True, "status": "CLAIMED"}

    limit = db.query(WheelDailyLimit).filter_by(telegram_id=1001).one()
    assert limit.rewarded_ad_spins == 1
    assert limit.last_ad_spin_at == NOW


def test_duplicate_ymid_and_replayed_postback_never_duplicate_reward(client, db):
    assert create_session(client).status_code == 200
    assert create_session(client).status_code == 409
    assert postback(client).json()["rewarded"] is True
    replay = postback(client)
    assert replay.status_code == 200
    assert replay.json()["rewarded"] is False
    assert db.query(WheelDailyLimit).filter_by(telegram_id=1001).one().rewarded_ad_spins == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event", "click"),
        ("value", "non_valued"),
        ("source", "other"),
        ("telegram_id", 2002),
    ],
)
def test_invalid_postback_conditions_do_not_reward(client, db, field, value):
    assert create_session(client).status_code == 200
    response = postback(client, **{field: value})
    assert response.status_code == 200
    assert response.json()["rewarded"] is False
    assert db.query(WheelDailyLimit).filter_by(telegram_id=1001).one().rewarded_ad_spins == 0


def test_unknown_ymid_and_status_ownership_do_not_reward(client, db):
    response = postback(client)
    assert response.status_code == 200
    assert response.json()["status"] == "IGNORED"
    assert db.query(WheelDailyLimit).count() == 0

    assert create_session(client).status_code == 200
    assert client.get(
        f"/api/ads/monetag/status/{YMID}",
        headers=auth_headers(1001),
    ).json()["status"] == "PENDING"
    assert client.get(f"/api/ads/monetag/status/{YMID}").status_code == 401
