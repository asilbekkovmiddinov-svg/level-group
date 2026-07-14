from types import SimpleNamespace

from app.routers import user as user_router


def test_user_seen_returns_authenticated_telegram_id(monkeypatch):
    monkeypatch.setattr(user_router, "mark_internal_user_seen", lambda db, telegram_id: True)
    current_user = SimpleNamespace(telegram_id=123456789)
    response = user_router.user_seen(current_user=current_user, db=object())
    assert response == {
        "success": True,
        "message": "User last seen updated",
        "telegram_id": 123456789,
    }
