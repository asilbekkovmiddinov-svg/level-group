from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import config
from app.routers.support import normalize_support_username, router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_public_support_config_returns_normalized_environment_username(monkeypatch):
    monkeypatch.setattr(config, "SUPPORT_TELEGRAM_USERNAME", "  @Level_Group_Admin ")

    response = client().get("/support/config")

    assert response.status_code == 200
    assert response.json() == {
        "support_telegram_username": "Level_Group_Admin",
    }


def test_missing_or_invalid_support_username_returns_safe_empty_value(monkeypatch):
    for value in (None, "", "@bad-name", "four", "a" * 33):
        monkeypatch.setattr(config, "SUPPORT_TELEGRAM_USERNAME", value)
        response = client().get("/support/config")
        assert response.status_code == 200
        assert response.json() == {"support_telegram_username": None}


def test_support_username_is_never_hardcoded():
    assert normalize_support_username("@Valid_Name") == "Valid_Name"
    assert normalize_support_username("invalid/name") is None
