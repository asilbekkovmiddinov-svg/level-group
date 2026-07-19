import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import admin_auth, telegram_auth
from app.core.database import Base, get_db
from app.models.promotion import Promotion
from app.routers import promotion, promotion_banner
from app.routers.promotion import admin_router
from app.routers.promotion_banner import router as banner_router
from app.services.promotion_banners import MAX_PROMOTION_BANNER_SIZE


def init_data(telegram_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Banner Admin"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def build_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Promotion.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(admin_auth, "ADMIN_TELEGRAM_IDS", frozenset({9001}))
    uploaded = []
    deleted = []
    monkeypatch.setattr(promotion_banner, "upload_object", lambda key, content, content_type: uploaded.append((key, content, content_type)))
    monkeypatch.setattr(promotion_banner, "delete_object", lambda key: deleted.append(key))
    monkeypatch.setattr(promotion, "generate_presigned_get_url", lambda key: f"https://signed.example/{key}")
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(banner_router)

    def dependency():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = dependency
    db = sessions()
    db.add(Promotion(title="Banner promo", status="DRAFT", button_action="NONE", priority=1))
    db.commit()
    promotion_id = db.query(Promotion.id).scalar()
    db.close()
    return TestClient(app), sessions, promotion_id, uploaded, deleted


def headers(telegram_id=9001):
    return {"X-Telegram-Init-Data": init_data(telegram_id)}


def test_banner_upload_replace_delete_and_verified_actor(monkeypatch):
    client, sessions, promotion_id, uploaded, deleted = build_client(monkeypatch)
    first = client.post(
        f"/admin/promotions/{promotion_id}/banner",
        headers=headers(),
        files={"file": ("banner.jpg", b"\xff\xd8\xfffirst", "image/jpeg")},
    )
    assert first.status_code == 200
    assert first.json()["banner_uploaded"] is True
    assert first.json()["banner_url"].startswith("https://signed.example/promotions/")
    assert first.json()["updated_by"] == 9001
    assert len(uploaded) == 1
    old_key = uploaded[0][0]

    replacement = client.post(
        f"/admin/promotions/{promotion_id}/banner",
        headers=headers(),
        files={"file": ("banner.webp", b"RIFF0000WEBPreplacement", "image/webp")},
    )
    assert replacement.status_code == 200
    assert len(uploaded) == 2
    assert deleted == [old_key]

    current_key = uploaded[1][0]
    removed = client.delete(f"/admin/promotions/{promotion_id}/banner", headers=headers())
    assert removed.status_code == 200
    assert removed.json()["banner_uploaded"] is False
    assert removed.json()["banner_url"] is None
    assert deleted == [old_key, current_key]
    db = sessions()
    stored = db.get(Promotion, promotion_id)
    assert stored.banner_object_key is None
    assert stored.updated_by == 9001
    db.close()


def test_banner_endpoints_require_admin_init_data(monkeypatch):
    client, _, promotion_id, _, _ = build_client(monkeypatch)
    file = {"file": ("banner.png", b"\x89PNG\r\n\x1a\nimage", "image/png")}
    assert client.post(f"/admin/promotions/{promotion_id}/banner", files=file).status_code == 401
    assert client.post(
        f"/admin/promotions/{promotion_id}/banner",
        headers=headers(7777),
        files=file,
    ).status_code == 403


def test_banner_validation_rejects_type_signature_and_size(monkeypatch):
    client, _, promotion_id, uploaded, _ = build_client(monkeypatch)
    invalid = client.post(
        f"/admin/promotions/{promotion_id}/banner",
        headers=headers(),
        files={"file": ("banner.gif", b"GIF89a", "image/gif")},
    )
    assert invalid.status_code == 400
    mismatch = client.post(
        f"/admin/promotions/{promotion_id}/banner",
        headers=headers(),
        files={"file": ("banner.jpg", b"not-jpeg", "image/jpeg")},
    )
    assert mismatch.status_code == 400
    oversized = client.post(
        f"/admin/promotions/{promotion_id}/banner",
        headers=headers(),
        files={"file": ("banner.jpg", b"\xff\xd8\xff" + b"x" * MAX_PROMOTION_BANNER_SIZE, "image/jpeg")},
    )
    assert oversized.status_code == 413
    assert uploaded == []
