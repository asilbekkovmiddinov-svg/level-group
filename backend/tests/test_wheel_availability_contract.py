from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.crud import wheel
from app.models.user import User
from app.models.wheel import WheelSpin


NOW = datetime(2030, 1, 2, 12, 0, 0)


def test_free_spin_uses_exact_24_hour_cooldown():
    used_at = NOW - timedelta(hours=23, minutes=59, seconds=59)
    available, next_at, remaining = wheel.get_cooldown_status(
        used_at,
        timedelta(hours=24),
        NOW,
    )
    assert available is False
    assert next_at == "2030-01-02T12:00:01Z"
    assert remaining == 0

    assert wheel.get_cooldown_status(
        NOW - timedelta(hours=24),
        timedelta(hours=24),
        NOW,
    ) == (True, None, 1)


def test_ad_spin_uses_exact_one_hour_cooldown_without_daily_cap():
    limit = SimpleNamespace(
        last_ad_spin_at=NOW - timedelta(minutes=59, seconds=59),
        ad_spin_count=99,
        bonus_spin_count=0,
    )
    allowed, error = wheel.can_spin(limit, wheel.SPIN_TYPE_AD, now=NOW)
    assert allowed is False
    assert "2030-01-02T12:00:01Z" in error

    limit.last_ad_spin_at = NOW - timedelta(hours=1)
    assert wheel.can_spin(limit, wheel.SPIN_TYPE_AD, now=NOW) == (True, None)


def test_status_exposes_new_availability_contract(monkeypatch):
    limit = SimpleNamespace(
        free_spin_used=True,
        ad_spin_count=3,
        bonus_spin_count=0,
        last_ad_spin_at=NOW - timedelta(minutes=30),
    )
    settings = SimpleNamespace(global_spin_count=42)
    monkeypatch.setattr(wheel, "get_or_create_daily_limit", lambda _db, _id: limit)
    monkeypatch.setattr(wheel, "get_or_create_settings", lambda _db: settings)
    monkeypatch.setattr(wheel, "get_last_free_spin_at", lambda _db, _id: NOW - timedelta(hours=12))
    monkeypatch.setattr(wheel, "get_last_completed_spin", lambda _db, _id: None)
    monkeypatch.setattr(wheel, "get_now", lambda: NOW)

    status = wheel.get_wheel_status(object(), 123)

    assert status["free_spin_available"] is False
    assert status["next_free_spin_at"] == "2030-01-03T00:00:00Z"
    assert status["remaining_free_spins"] == 0
    assert status["ad_spin_available"] is False
    assert status["next_ad_spin_at"] == "2030-01-02T12:30:00Z"
    assert status["remaining_ad_spins"] == 0
    assert status["server_time"] == "2030-01-02T12:00:00Z"
    assert status["last_win"] is None


def test_status_becomes_ready_when_both_cooldowns_expire(monkeypatch):
    limit = SimpleNamespace(
        free_spin_used=True,
        ad_spin_count=20,
        bonus_spin_count=0,
        last_ad_spin_at=NOW - timedelta(hours=1),
    )
    monkeypatch.setattr(wheel, "get_or_create_daily_limit", lambda _db, _id: limit)
    monkeypatch.setattr(
        wheel,
        "get_or_create_settings",
        lambda _db: SimpleNamespace(global_spin_count=100),
    )
    monkeypatch.setattr(
        wheel,
        "get_last_free_spin_at",
        lambda _db, _id: NOW - timedelta(hours=24),
    )
    monkeypatch.setattr(wheel, "get_last_completed_spin", lambda _db, _id: None)
    monkeypatch.setattr(wheel, "get_now", lambda: NOW)

    status = wheel.get_wheel_status(object(), 123)

    assert status["free_spin_available"] is True
    assert status["next_free_spin_at"] is None
    assert status["remaining_free_spins"] == 1
    assert status["ad_spin_available"] is True
    assert status["next_ad_spin_at"] is None
    assert status["remaining_ad_spins"] == 1


def test_status_persists_last_completed_win_across_reloads(monkeypatch):
    limit = SimpleNamespace(
        free_spin_used=True,
        ad_spin_count=1,
        bonus_spin_count=0,
        last_ad_spin_at=NOW - timedelta(minutes=30),
    )
    last_spin = SimpleNamespace(
        reward_type=wheel.REWARD_TYPE_UZS,
        reward_amount=Decimal("500.0000"),
        reward_code="uzs_500",
        created_at=NOW - timedelta(minutes=5),
    )
    monkeypatch.setattr(wheel, "get_or_create_daily_limit", lambda _db, _id: limit)
    monkeypatch.setattr(
        wheel,
        "get_or_create_settings",
        lambda _db: SimpleNamespace(global_spin_count=42),
    )
    monkeypatch.setattr(wheel, "get_last_free_spin_at", lambda _db, _id: NOW - timedelta(hours=1))
    monkeypatch.setattr(wheel, "get_last_completed_spin", lambda _db, _id: last_spin)
    monkeypatch.setattr(wheel, "get_now", lambda: NOW)

    first_load = wheel.get_wheel_status(object(), 123)
    reload = wheel.get_wheel_status(object(), 123)

    expected = {
        "reward_type": "UZS",
        "reward_amount": 500.0,
        "reward_code": "uzs_500",
        "created_at": "2030-01-02T11:55:00Z",
    }
    assert first_load["last_win"] == expected
    assert reload["last_win"] == expected


def test_last_win_uses_latest_completed_spin_for_requested_user():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, WheelSpin.__table__])
    session = sessionmaker(bind=engine)()
    try:
        session.add_all(
            [
                WheelSpin(
                    id=1,
                    telegram_id=123,
                    spin_type=wheel.SPIN_TYPE_FREE,
                    reward_code="efc_50",
                    reward_type=wheel.REWARD_TYPE_EFC,
                    reward_amount=Decimal("50"),
                    global_spin_number=1,
                    status=wheel.STATUS_COMPLETED,
                    created_at=NOW - timedelta(minutes=20),
                ),
                WheelSpin(
                    id=2,
                    telegram_id=123,
                    spin_type=wheel.SPIN_TYPE_AD,
                    reward_code="uzs_5000",
                    reward_type=wheel.REWARD_TYPE_UZS,
                    reward_amount=Decimal("5000"),
                    global_spin_number=2,
                    status="FAILED",
                    created_at=NOW - timedelta(minutes=5),
                ),
                WheelSpin(
                    id=3,
                    telegram_id=999,
                    spin_type=wheel.SPIN_TYPE_FREE,
                    reward_code="coin_2000_jackpot",
                    reward_type=wheel.REWARD_TYPE_COIN_ORDER,
                    reward_amount=Decimal("2000"),
                    global_spin_number=3,
                    status=wheel.STATUS_COMPLETED,
                    created_at=NOW - timedelta(minutes=2),
                ),
                WheelSpin(
                    id=4,
                    telegram_id=123,
                    spin_type=wheel.SPIN_TYPE_AD,
                    reward_code="efc_100",
                    reward_type=wheel.REWARD_TYPE_EFC,
                    reward_amount=Decimal("100"),
                    global_spin_number=4,
                    status=wheel.STATUS_COMPLETED,
                    created_at=NOW - timedelta(minutes=10),
                ),
            ]
        )
        session.commit()

        last_win = wheel.get_last_completed_spin(session, 123)

        assert last_win.id == 4
        assert wheel.serialize_last_win(last_win) == {
            "reward_type": "EFC",
            "reward_amount": 100.0,
            "reward_code": "efc_100",
            "created_at": "2030-01-02T11:50:00Z",
        }
    finally:
        session.close()
        engine.dispose()
