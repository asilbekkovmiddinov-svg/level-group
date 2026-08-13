import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
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
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.models.wheel import AdsgramRewardSession, WheelDailyLimit
from app.routers import wheel as wheel_router
from app.routers import wall_rush as wall_rush_router
from app.services import adsgram_reward


NOW = datetime(2030, 1, 2, 12, 0)


def auth_headers(telegram_id: int) -> dict[str, str]:
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
            GameTicketWallet.__table__,
            GameTicketLedger.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    session.add(User(telegram_id=1001, first_name="Adsgram User"))
    session.commit()
    monkeypatch.setattr(adsgram_reward, "utc_now", lambda: NOW)
    monkeypatch.setattr(wheel, "get_now", lambda: NOW)
    monkeypatch.setattr(wheel, "get_today", lambda: NOW.date())
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_reward_requires_server_verification_and_can_be_claimed_once(db):
    session, token = adsgram_reward.create_reward_session(db, 1001)

    with pytest.raises(ValueError, match="hali kelmadi"):
        adsgram_reward.claim_reward(db, 1001, token)

    verified = adsgram_reward.verify_adsgram_callback(db, 1001)
    assert verified.id == session.id
    claimed = adsgram_reward.claim_reward(db, 1001, token)
    assert claimed.status == adsgram_reward.CLAIMED

    limit = db.query(WheelDailyLimit).filter_by(telegram_id=1001).one()
    assert limit.rewarded_ad_spins == 1
    assert wheel.can_spin(limit, wheel.SPIN_TYPE_AD, now=NOW) == (True, None)

    with pytest.raises(ValueError, match="allaqachon"):
        adsgram_reward.claim_reward(db, 1001, token)
    db.refresh(limit)
    assert limit.rewarded_ad_spins == 1


def test_replayed_callback_and_expired_session_never_add_reward(db):
    session, token = adsgram_reward.create_reward_session(db, 1001)
    assert adsgram_reward.verify_adsgram_callback(db, 1001).id == session.id
    assert adsgram_reward.verify_adsgram_callback(db, 1001) is None

    session.expires_at = NOW - timedelta(seconds=1)
    db.commit()
    with pytest.raises(ValueError, match="eskirgan"):
        adsgram_reward.claim_reward(db, 1001, token)

    limit = db.query(WheelDailyLimit).filter_by(telegram_id=1001).one()
    assert limit.rewarded_ad_spins == 0


def test_wall_rush_adsgram_reward_is_scoped_and_granted_exactly_once(db):
    session, token = adsgram_reward.create_wall_rush_reward_session(db, 1001)
    assert session.purpose == adsgram_reward.WALL_RUSH_PURPOSE

    with pytest.raises(ValueError, match="hali kelmadi"):
        adsgram_reward.claim_wall_rush_reward(db, 1001, token)

    assert adsgram_reward.verify_adsgram_callback(db, 1001).id == session.id
    with pytest.raises(ValueError, match="bu o‘yin uchun"):
        adsgram_reward.claim_reward(db, 1001, token)

    claimed, wallet = adsgram_reward.claim_wall_rush_reward(db, 1001, token)
    assert claimed.status == adsgram_reward.CLAIMED
    assert wallet.game_tickets == 1

    with pytest.raises(ValueError, match="allaqachon"):
        adsgram_reward.claim_wall_rush_reward(db, 1001, token)
    db.expire_all()
    assert db.get(GameTicketWallet, 1001).game_tickets == 1
    assert db.query(GameTicketLedger).filter_by(operation="AD_GRANT").count() == 1

    with pytest.raises(ValueError, match="cooldown"):
        adsgram_reward.create_wall_rush_reward_session(db, 1001)


def test_failed_wall_rush_adsgram_session_can_be_cancelled_before_tads(db):
    session, token = adsgram_reward.create_wall_rush_reward_session(db, 1001)
    cancelled = adsgram_reward.cancel_wall_rush_reward_session(db, 1001, token)

    assert cancelled.id == session.id
    assert cancelled.status == adsgram_reward.EXPIRED
    assert adsgram_reward.verify_adsgram_callback(db, 1001) is None

    replacement, _ = adsgram_reward.create_wall_rush_reward_session(db, 1001)
    assert replacement.id != session.id
    assert replacement.status == adsgram_reward.PENDING


def test_reward_routes_require_authentication_and_server_callback(db, monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(wheel_router, "ADSGRAM_REWARD_SECRET", "callback-secret")

    app = FastAPI()
    app.include_router(wheel_router.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    assert client.post("/wheel/adsgram/session").status_code == 401
    issued = client.post("/wheel/adsgram/session", headers=auth_headers(1001))
    assert issued.status_code == 200
    token = issued.json()["token"]

    pending = client.post(
        "/wheel/adsgram/claim",
        json={"token": token},
        headers=auth_headers(1001),
    )
    assert pending.status_code == 425
    assert client.get(
        "/wheel/adsgram/reward",
        params={"user_id": 1001, "key": "wrong"},
    ).status_code == 401

    verified = client.get(
        "/wheel/adsgram/reward",
        params={"user_id": 1001, "key": "callback-secret"},
    )
    assert verified.status_code == 200
    assert verified.json() == {"success": True, "verified": True}

    claimed = client.post(
        "/wheel/adsgram/claim",
        json={"token": token},
        headers=auth_headers(1001),
    )
    assert claimed.status_code == 200
    assert claimed.json()["remaining_ad_spins"] == 1
    duplicate = client.post(
        "/wheel/adsgram/claim",
        json={"token": token},
        headers=auth_headers(1001),
    )
    assert duplicate.status_code == 409

    db.expire_all()
    limit = db.query(WheelDailyLimit).filter_by(telegram_id=1001).one()
    assert limit.rewarded_ad_spins == 1


def test_wall_rush_adsgram_routes_use_auth_callback_and_server_wallet(db, monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(wheel_router, "ADSGRAM_REWARD_SECRET", "callback-secret")

    app = FastAPI()
    app.include_router(wheel_router.router)
    app.include_router(wall_rush_router.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    assert client.post("/wall-rush/rewards/adsgram/session").status_code == 401
    issued = client.post(
        "/wall-rush/rewards/adsgram/session",
        headers=auth_headers(1001),
    )
    assert issued.status_code == 200
    token = issued.json()["token"]

    pending = client.post(
        "/wall-rush/rewards/adsgram/claim",
        json={"token": token},
        headers=auth_headers(1001),
    )
    assert pending.status_code == 425

    verified = client.get(
        "/wheel/adsgram/reward",
        params={"user_id": 1001, "key": "callback-secret"},
    )
    assert verified.json() == {"success": True, "verified": True}

    claimed = client.post(
        "/wall-rush/rewards/adsgram/claim",
        json={"token": token},
        headers=auth_headers(1001),
    )
    assert claimed.status_code == 200
    assert claimed.json()["wallet"]["game_tickets"] == 1

    duplicate = client.post(
        "/wall-rush/rewards/adsgram/claim",
        json={"token": token},
        headers=auth_headers(1001),
    )
    assert duplicate.status_code == 409
    assert db.get(GameTicketWallet, 1001).game_tickets == 1
