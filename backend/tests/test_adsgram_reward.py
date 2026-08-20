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
from app.routers import penalty_duel_ads as penalty_duel_ads_router
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
    monkeypatch.setattr(penalty_duel_ads_router.config, "TADS_WEBHOOK_SECRET", "tads-secret")
    monkeypatch.setattr(penalty_duel_ads_router.config, "TADS_WALL_RUSH_WIDGET_ID", "11416")
    monkeypatch.setattr(penalty_duel_ads_router.config, "TELEGA_REWARD_SECRET", "telega-secret")
    monkeypatch.setattr(
        penalty_duel_ads_router.config, "TELEGA_MINIAPP_TOKEN", "test-client-token",
    )
    monkeypatch.setattr(
        penalty_duel_ads_router.config, "TELEGA_REWARDED_AD_BLOCK_UUID", "test-block",
    )
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


def test_wall_rush_adsgram_reward_is_scoped_and_granted_exactly_once(db, monkeypatch):
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

    monkeypatch.setattr(
        adsgram_reward, "utc_now", lambda: NOW + timedelta(minutes=29)
    )
    with pytest.raises(ValueError, match="cooldown"):
        adsgram_reward.create_wall_rush_reward_session(db, 1001)

    monkeypatch.setattr(
        adsgram_reward, "utc_now", lambda: NOW + timedelta(minutes=30)
    )
    next_session, _ = adsgram_reward.create_wall_rush_reward_session(db, 1001)
    assert next_session.purpose == adsgram_reward.WALL_RUSH_PURPOSE


def test_failed_wall_rush_adsgram_session_can_be_cancelled_before_tads(db):
    session, token = adsgram_reward.create_wall_rush_reward_session(db, 1001)
    cancelled = adsgram_reward.cancel_wall_rush_reward_session(db, 1001, token)

    assert cancelled.id == session.id
    assert cancelled.status == adsgram_reward.EXPIRED
    assert adsgram_reward.verify_adsgram_callback(db, 1001) is None

    replacement, _ = adsgram_reward.create_wall_rush_reward_session(db, 1001)
    assert replacement.id != session.id
    assert replacement.status == adsgram_reward.PENDING


def test_penalty_duel_adsgram_uses_separate_five_minute_rotation(db, monkeypatch):
    session, token = adsgram_reward.create_penalty_duel_reward_session(db, 1001)
    assert session.purpose == adsgram_reward.PENALTY_DUEL_PURPOSE
    assert adsgram_reward.verify_adsgram_callback(db, 1001).id == session.id

    claimed, wallet = adsgram_reward.claim_penalty_duel_reward(db, 1001, token)
    assert claimed.status == adsgram_reward.CLAIMED
    assert wallet.game_tickets == 1
    assert wallet.penalty_duel_rewarded_ad_provider_index == 1
    assert wallet.last_rewarded_ad_at is None

    monkeypatch.setattr(
        adsgram_reward, "utc_now", lambda: NOW + timedelta(minutes=4, seconds=59)
    )
    with pytest.raises(ValueError, match="cooldown"):
        adsgram_reward.create_penalty_duel_reward_session(db, 1001)

    monkeypatch.setattr(
        adsgram_reward, "utc_now", lambda: NOW + timedelta(minutes=5)
    )
    next_session, _ = adsgram_reward.create_penalty_duel_reward_session(db, 1001)
    assert next_session.purpose == adsgram_reward.PENALTY_DUEL_PURPOSE


def test_adsgram_callback_never_verifies_a_tads_session(db):
    session, _ = adsgram_reward.create_tads_penalty_duel_reward_session(db, 1001)

    assert adsgram_reward.verify_adsgram_callback(db, 1001) is None
    db.refresh(session)
    assert session.status == adsgram_reward.PENDING


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


def test_penalty_duel_adsgram_routes_are_scoped_and_exactly_once(db, monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(
        penalty_duel_ads_router.config, "ONCLICKA_REWARDED_AD_ENABLED", False,
    )
    monkeypatch.setattr(wheel_router, "ADSGRAM_REWARD_SECRET", "callback-secret")
    monkeypatch.setattr(
        penalty_duel_ads_router.config, "TELEGA_MINIAPP_TOKEN", "test-client-token",
    )

    app = FastAPI()
    app.include_router(wheel_router.router)
    app.include_router(penalty_duel_ads_router.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    assert client.get("/penalty-duel/rewards/config").status_code == 401
    ad_config = client.get(
        "/penalty-duel/rewards/config", headers=auth_headers(1001),
    )
    assert ad_config.status_code == 200
    assert ad_config.json()["telega_token"] == "test-client-token"
    assert ad_config.json()["providers"] == ["ADSGRAM", "TADS", "TELEGA"]
    assert ad_config.json()["onclicka_enabled"] is False
    assert ad_config.json()["onclicka_spot_id"] == ""
    disabled_onclicka = client.post(
        "/penalty-duel/rewards/onclicka/session",
        headers=auth_headers(1001),
    )
    assert disabled_onclicka.status_code == 503

    issued = client.post(
        "/penalty-duel/rewards/adsgram/session",
        headers=auth_headers(1001),
    )
    assert issued.status_code == 200
    token = issued.json()["token"]

    pending = client.post(
        "/penalty-duel/rewards/adsgram/claim",
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
        "/penalty-duel/rewards/adsgram/claim",
        json={"token": token},
        headers=auth_headers(1001),
    )
    assert claimed.status_code == 200
    assert claimed.json()["wallet"]["game_tickets"] == 1
    duplicate = client.post(
        "/penalty-duel/rewards/adsgram/claim",
        json={"token": token},
        headers=auth_headers(1001),
    )
    assert duplicate.status_code == 409
    assert db.get(GameTicketWallet, 1001).game_tickets == 1


def test_penalty_duel_tads_session_routes_are_authenticated_and_cancellable(db, monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")

    app = FastAPI()
    app.include_router(penalty_duel_ads_router.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    assert client.post("/penalty-duel/rewards/tads/session").status_code == 401
    issued = client.post(
        "/penalty-duel/rewards/tads/session", headers=auth_headers(1001),
    )
    assert issued.status_code == 200
    token = issued.json()["token"]

    cancelled = client.post(
        "/penalty-duel/rewards/tads/cancel",
        json={"token": token},
        headers=auth_headers(1001),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == adsgram_reward.EXPIRED


def test_onclicka_session_routes_are_authenticated_and_cancellable(db, monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    opaque_token = "opaque-token-0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(
        penalty_duel_ads_router.config, "ONCLICKA_REWARD_SECRET", opaque_token,
    )
    monkeypatch.setattr(
        penalty_duel_ads_router.config, "ONCLICKA_REWARDED_AD_ENABLED", True,
    )

    app = FastAPI()
    app.include_router(penalty_duel_ads_router.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    assert client.post("/penalty-duel/rewards/onclicka/session").status_code == 401
    enabled_config = client.get(
        "/penalty-duel/rewards/config", headers=auth_headers(1001),
    )
    assert enabled_config.json()["providers"] == [
        "ADSGRAM", "TADS", "TELEGA", "ONCLICKA",
    ]
    assert enabled_config.json()["onclicka_enabled"] is True
    issued = client.post(
        "/penalty-duel/rewards/onclicka/session",
        headers=auth_headers(1001),
    )
    assert issued.status_code == 200
    token = issued.json()["token"]

    cancelled = client.post(
        "/penalty-duel/rewards/onclicka/cancel",
        json={"token": token},
        headers=auth_headers(1001),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == adsgram_reward.EXPIRED

    callback = client.get(
        f"/penalty-duel/rewards/onclicka/callback/{opaque_token}",
        params={"USERID": 1001},
    )
    assert callback.status_code == 200
    assert callback.json()["rewarded"] is False
    assert db.get(GameTicketWallet, 1001).game_tickets == 0


def test_incomplete_onclicka_env_never_enters_production_rotation(db, monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(
        penalty_duel_ads_router.config, "ONCLICKA_REWARDED_AD_ENABLED", True,
    )
    monkeypatch.setattr(
        penalty_duel_ads_router.config, "ONCLICKA_REWARD_SECRET", "",
    )

    app = FastAPI()
    app.include_router(penalty_duel_ads_router.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    ad_config = client.get(
        "/penalty-duel/rewards/config", headers=auth_headers(1001),
    )
    assert ad_config.status_code == 200
    assert ad_config.json()["providers"] == ["ADSGRAM", "TADS", "TELEGA"]
    assert ad_config.json()["onclicka_enabled"] is False
    assert client.post(
        "/penalty-duel/rewards/onclicka/session",
        headers=auth_headers(1001),
    ).status_code == 503


def test_incomplete_tads_and_telega_env_are_not_advertised(db, monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(penalty_duel_ads_router.config, "TADS_WEBHOOK_SECRET", "")
    monkeypatch.setattr(penalty_duel_ads_router.config, "TELEGA_REWARD_SECRET", "")

    app = FastAPI()
    app.include_router(penalty_duel_ads_router.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    ad_config = client.get(
        "/penalty-duel/rewards/config", headers=auth_headers(1001),
    )
    assert ad_config.status_code == 200
    assert ad_config.json()["providers"] == ["ADSGRAM"]
    assert ad_config.json()["tads_widget_id"] == ""
    assert ad_config.json()["telega_token"] == ""
    assert ad_config.json()["tads_enabled"] is False
    assert ad_config.json()["telega_enabled"] is False
