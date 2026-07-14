import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core import config, telegram_auth
from app.core.arena_internal_auth import require_arena_internal_api_key
from app.core.database import get_db
from app.routers import match as match_router


INTERNAL_ENDPOINTS = {
    ("/matches/worker/due-scheduled", "GET"),
    ("/matches/worker/expired-ready", "GET"),
    ("/matches/worker/timeouts/run", "POST"),
    ("/matches/{match_id}/start-ready-check", "POST"),
    ("/matches/{match_id}/finish-ready-check", "POST"),
    ("/matches/{match_id}/resolve", "POST"),
    ("/matches/internal/evidence", "POST"),
}


def headers(telegram_id=1001):
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Ali"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(values)}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_API_KEY", "arena-internal-test-key")
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(match_router.match_crud, "get_due_scheduled_matches", lambda **_: [])
    monkeypatch.setattr(match_router.match_crud, "get_open_matches", lambda **_: [])

    app = FastAPI()
    app.include_router(match_router.router)
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


def test_internal_dependency_accepts_only_matching_key(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_API_KEY", "arena-internal-test-key")

    assert require_arena_internal_api_key("arena-internal-test-key") is None
    for provided_key in (None, "wrong-key"):
        with pytest.raises(HTTPException) as error:
            require_arena_internal_api_key(provided_key)
        assert error.value.status_code == 401


def test_all_legacy_worker_and_admin_routes_use_internal_dependency():
    protected = set()
    for route in match_router.router.routes:
        methods = route.methods or set()
        dependency_calls = {item.call for item in route.dependant.dependencies}
        for method in methods:
            if require_arena_internal_api_key in dependency_calls:
                protected.add((route.path, method))

    assert INTERNAL_ENDPOINTS <= protected


def test_worker_rejects_missing_invalid_and_user_init_data(client):
    path = "/matches/worker/due-scheduled"

    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Internal-Api-Key": "wrong-key"}).status_code == 401
    assert client.get(path, headers=headers(1001)).status_code == 401


def test_internal_auth_success_and_public_auth_still_work(client):
    internal = client.get(
        "/matches/worker/due-scheduled",
        headers={"X-Internal-Api-Key": "arena-internal-test-key"},
    )
    assert internal.status_code == 200
    assert internal.json() == {"matches": []}

    public = client.get("/matches/open", headers=headers(1001))
    assert public.status_code == 200
    assert public.json() == {"matches": []}
