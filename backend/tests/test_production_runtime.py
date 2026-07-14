import pytest
from fastapi import HTTPException

from app.core import config
from app.core.observability import enforce_rate_limit, metrics_snapshot
from app.core.runtime import REQUIRED_PRODUCTION_SETTINGS, validate_startup_settings


def test_startup_validation_lists_all_missing_required_settings(monkeypatch):
    for name in REQUIRED_PRODUCTION_SETTINGS: monkeypatch.setattr(config, name, None)
    with pytest.raises(RuntimeError) as error: validate_startup_settings()
    assert all(name in str(error.value) for name in REQUIRED_PRODUCTION_SETTINGS)


def test_startup_validation_accepts_complete_environment(monkeypatch):
    for name in REQUIRED_PRODUCTION_SETTINGS: monkeypatch.setattr(config, name, "configured")
    validate_startup_settings()


def test_wallet_rate_limit_is_per_user_and_observable():
    operation = "test-operation-production-runtime"
    enforce_rate_limit(7001, operation, 2); enforce_rate_limit(7001, operation, 2)
    with pytest.raises(HTTPException) as error: enforce_rate_limit(7001, operation, 2)
    assert error.value.status_code == 429
    enforce_rate_limit(7002, operation, 2)
    assert metrics_snapshot()["wallet_rate_limit_rejections_total"] >= 1
