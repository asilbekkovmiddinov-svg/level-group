import pytest
from fastapi import HTTPException

from app.routers import internal_wallet
from app.routers import system


def test_internal_api_key_requirement_rejects_missing_and_invalid_keys(monkeypatch):
    monkeypatch.setattr(internal_wallet, "INTERNAL_API_KEY", "test-key")

    for provided_key in (None, "wrong-key"):
        with pytest.raises(HTTPException) as error:
            internal_wallet.require_internal_api_key(provided_key)
        assert error.value.status_code == 403


def test_internal_api_key_requirement_accepts_matching_key(monkeypatch):
    monkeypatch.setattr(internal_wallet, "INTERNAL_API_KEY", "test-key")

    assert internal_wallet.require_internal_api_key("test-key") is None


def test_public_migration_routes_require_internal_api_key():
    migration_routes = {
        route.path: route
        for route in system.router.routes
        if route.path in {"/system/migrate-orders", "/system/migrate-deposits"}
    }
    assert set(migration_routes) == {"/system/migrate-orders", "/system/migrate-deposits"}
    for route in migration_routes.values():
        dependencies = [dependency.call for dependency in route.dependant.dependencies]
        assert internal_wallet.require_internal_api_key in dependencies
