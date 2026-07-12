from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, status

from app.core.config import BOT_TOKEN, TELEGRAM_INIT_DATA_MAX_AGE_SECONDS


@dataclass(frozen=True)
class TelegramUser:
    telegram_id: int
    first_name: str
    username: str | None
    language: str


def _unauthorized(detail: str = "Invalid Telegram authentication data") -> None:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def verify_init_data(init_data: str) -> TelegramUser:
    if not BOT_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram authentication is not configured",
        )

    try:
        values = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received_hash = values.pop("hash")
        auth_date = int(values["auth_date"])
        raw_user = values["user"]
    except (KeyError, TypeError, ValueError):
        _unauthorized()

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        _unauthorized()

    now = int(time.time())
    if (
        auth_date > now + 30
        or now - auth_date > TELEGRAM_INIT_DATA_MAX_AGE_SECONDS
    ):
        _unauthorized("Telegram authentication data has expired")

    try:
        user = json.loads(raw_user)
        telegram_id = int(user["id"])
        first_name = str(user["first_name"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        _unauthorized()

    if telegram_id <= 0 or not first_name:
        _unauthorized()

    username = user.get("username")
    language = user.get("language_code") or "uz"
    return TelegramUser(
        telegram_id=telegram_id,
        first_name=first_name,
        username=str(username) if username else None,
        language=str(language),
    )


def get_current_telegram_user(
    x_telegram_init_data: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> TelegramUser:
    init_data = x_telegram_init_data
    if not init_data and authorization and authorization.startswith("tma "):
        init_data = authorization[4:]

    if not init_data:
        _unauthorized("Telegram authentication data is required")

    return verify_init_data(init_data)
