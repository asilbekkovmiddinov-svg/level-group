import json
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import TELEGRAM_BOT_TOKEN
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.routers.internal_wallet import require_internal_api_key
from app.schemas.subscription import (
    SubscriptionChannelCreate,
    SubscriptionChannelResponse,
    SubscriptionChannelUpdate,
)
from app.services.subscription_channels import (
    DEFAULT_REQUIRED_CHANNELS,
    SubscriptionChannelError,
    create_subscription_channel,
    delete_subscription_channel,
    list_subscription_channels,
    update_subscription_channel,
)


router = APIRouter(prefix="/subscription", tags=["Subscription"])
internal_router = APIRouter(
    prefix="/internal/subscription",
    tags=["Internal Subscription"],
    dependencies=[Depends(require_internal_api_key)],
)

# Compatibility name retained for old imports. Runtime checks use database rows.
REQUIRED_CHANNELS = DEFAULT_REQUIRED_CHANNELS
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


def _raise_channel_error(error: SubscriptionChannelError):
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.get("/status")
def subscription_status(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    missing = []
    try:
        for channel in list_subscription_channels(db):
            if not _is_member(channel.chat_id, current_user.telegram_id):
                missing.append({"title": channel.title, "url": channel.url})
    except (RuntimeError, urllib.error.URLError, TimeoutError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription verification is temporarily unavailable",
        )
    return {"subscribed": not missing, "missing_channels": missing}


@internal_router.get("/channels", response_model=list[SubscriptionChannelResponse])
def internal_list_channels(db: Session = Depends(get_db)):
    return list_subscription_channels(db)


@internal_router.post(
    "/channels",
    response_model=SubscriptionChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
def internal_create_channel(
    payload: SubscriptionChannelCreate, db: Session = Depends(get_db)
):
    try:
        return create_subscription_channel(db, payload)
    except SubscriptionChannelError as error:
        _raise_channel_error(error)


@internal_router.put("/channels/{channel_id}", response_model=SubscriptionChannelResponse)
def internal_update_channel(
    channel_id: int,
    payload: SubscriptionChannelUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_subscription_channel(db, channel_id, payload)
    except SubscriptionChannelError as error:
        _raise_channel_error(error)


@internal_router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def internal_delete_channel(channel_id: int, db: Session = Depends(get_db)):
    try:
        delete_subscription_channel(db, channel_id)
    except SubscriptionChannelError as error:
        _raise_channel_error(error)
