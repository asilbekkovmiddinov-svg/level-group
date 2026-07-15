from datetime import datetime, timedelta
from types import SimpleNamespace

from app.crud import wheel


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
    monkeypatch.setattr(wheel, "get_now", lambda: NOW)

    status = wheel.get_wheel_status(object(), 123)

    assert status["free_spin_available"] is False
    assert status["next_free_spin_at"] == "2030-01-03T00:00:00Z"
    assert status["remaining_free_spins"] == 0
    assert status["ad_spin_available"] is False
    assert status["next_ad_spin_at"] == "2030-01-02T12:30:00Z"
    assert status["remaining_ad_spins"] == 0
    assert status["server_time"] == "2030-01-02T12:00:00Z"


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
    monkeypatch.setattr(wheel, "get_now", lambda: NOW)

    status = wheel.get_wheel_status(object(), 123)

    assert status["free_spin_available"] is True
    assert status["next_free_spin_at"] is None
    assert status["remaining_free_spins"] == 1
    assert status["ad_spin_available"] is True
    assert status["next_ad_spin_at"] is None
    assert status["remaining_ad_spins"] == 1
