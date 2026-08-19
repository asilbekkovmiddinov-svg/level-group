import json
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import TELEGRAM_BOT_TOKEN
from app.core.telegram_auth import TelegramUser, get_current_telegram_user

router = APIRouter(prefix="/subscription", tags=["Subscription"])

REQUIRED_CHANNELS = (
    {"chat_id": "@Bek_PesserUz", "title": "Bek_PesserUz 🇺🇿", "url": "https://t.me/Bek_PesserUz"},
    {"chat_id": "@levelgroup_buyurtmalar", "title": "LEVEL | Completed Orders", "url": "https://t.me/levelgroup_buyurtmalar"},
    {"chat_id": "@ronin_Efootbol", "title": "RONIN eFootball", "url": "https://t.me/ronin_Efootbol"},
)
ALLOWED_STATUSES = {"creator", "administrator", "member", "restricted"}


def _is_member(chat_id: str, telegram_id: int) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Telegram bot token is not configured")
    query = urllib.parse.urlencode({"chat_id": chat_id, "user_id": telegram_id})
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChatMember?{query}"
    with urllib.request.urlopen(url, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError("Telegram membership verification failed")
    member = payload.get("result") or {}
    member_status = member.get("status")
    if member_status == "restricted":
        return bool(member.get("is_member"))
    return member_status in ALLOWED_STATUSES


@router.get("/status")
def subscription_status(
    current_user: TelegramUser = Depends(get_current_telegram_user),
):
    missing = []
    try:
        for channel in REQUIRED_CHANNELS:
            if not _is_member(channel["chat_id"], current_user.telegram_id):
                missing.append({"title": channel["title"], "url": channel["url"]})
    except (RuntimeError, urllib.error.URLError, TimeoutError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription verification is temporarily unavailable",
        )

    return {
        "subscribed": not missing,
        "missing_channels": missing,
    }
