import pytest
from fastapi import HTTPException

from app.routers import internal_wallet


def test_internal_api_key_requirement_rejects_missing_and_invalid_keys(monkeypatch):
    monkeypatch.setattr(internal_wallet, "INTERNAL_API_KEY", "test-key")

    for provided_key in (None, "wrong-key"):
        with pytest.raises(HTTPException) as error:
            internal_wallet.require_internal_api_key(provided_key)
        assert error.value.status_code == 403


def test_internal_api_key_requirement_accepts_matching_key(monkeypatch):
    monkeypatch.setattr(internal_wallet, "INTERNAL_API_KEY", "test-key")

    assert internal_wallet.require_internal_api_key("test-key") is None
