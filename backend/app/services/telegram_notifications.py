from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from uuid import uuid4

from app.core import config

CAPTION_LIMIT = 1024

class TelegramNotificationConfigError(RuntimeError): pass
class TelegramNotificationTimeoutError(RuntimeError): pass
class TelegramNotificationNetworkError(RuntimeError): pass
class TelegramNotificationRateLimitError(RuntimeError): pass
class TelegramNotificationPermanentError(RuntimeError): pass
class TelegramNotificationTemporaryError(RuntimeError): pass
class TelegramNotificationResponseError(RuntimeError): pass

@dataclass(frozen=True)
class TelegramPhotoResult:
    message_id: int
    chat_id: int | str

def _multipart(fields, filename, content_type, content):
    boundary = f"----LevelGroup{uuid4().hex}"; chunks = []
    for name, value in fields.items(): chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    chunks += [f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n".encode(), content, f"\r\n--{boundary}--\r\n".encode()]
    return boundary, b"".join(chunks)

def send_deposit_receipt_photo(receipt_bytes: bytes, content_type: str, filename: str, caption: str, chat_id: int | str | None = None, reply_markup: dict | None = None) -> TelegramPhotoResult:
    if not config.TELEGRAM_BOT_TOKEN or not (chat_id or config.ADMIN_DEPOSIT_CHANNEL_ID): raise TelegramNotificationConfigError("Telegram notification is not configured")
    if content_type not in {"image/jpeg", "image/png", "image/webp"} or not receipt_bytes: raise TelegramNotificationPermanentError("Invalid receipt image")
    target = chat_id or config.ADMIN_DEPOSIT_CHANNEL_ID
    fields = {"chat_id": target, "caption": caption[:CAPTION_LIMIT]}
    if reply_markup:
        fields["reply_markup"] = json.dumps(reply_markup, separators=(",", ":"))
    boundary, body = _multipart(fields, filename, content_type, receipt_bytes)
    request = urllib.request.Request(f"{config.TELEGRAM_API_BASE_URL.rstrip('/')}/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=config.TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS) as response: data = json.loads(response.read())
    except socket.timeout as error: raise TelegramNotificationTimeoutError("Telegram request timed out") from error
    except urllib.error.HTTPError as error:
        if error.code == 429: raise TelegramNotificationRateLimitError("Telegram rate limited") from error
        if error.code in {400, 401, 403}: raise TelegramNotificationPermanentError("Telegram rejected notification") from error
        raise TelegramNotificationTemporaryError("Telegram service unavailable") from error
    except (urllib.error.URLError, OSError) as error: raise TelegramNotificationNetworkError("Telegram network error") from error
    except (ValueError, json.JSONDecodeError) as error: raise TelegramNotificationResponseError("Telegram response is invalid") from error
    if not isinstance(data, dict) or not data.get("ok") or not data.get("result", {}).get("message_id"): raise TelegramNotificationResponseError("Telegram response is invalid")
    return TelegramPhotoResult(message_id=data["result"]["message_id"], chat_id=data["result"].get("chat", {}).get("id", target))
