from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Telegram WebApp initData is intentionally short lived.  The default is one
# day, but deployments can tighten it without changing the code.
TELEGRAM_INIT_DATA_MAX_AGE_SECONDS = int(
    os.getenv("TELEGRAM_INIT_DATA_MAX_AGE_SECONDS", "86400")
)

# Used only by trusted server-to-server clients (for example the bot) for
# internal wallet operations. It must never be exposed to the Mini App.
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
COIN_CREDENTIAL_ENCRYPTION_KEY = os.getenv("COIN_CREDENTIAL_ENCRYPTION_KEY")


def _telegram_id_allowlist(value: str | None) -> frozenset[int]:
    if not value or not value.strip():
        return frozenset()
    try:
        result = frozenset(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("ADMIN_TELEGRAM_IDS must contain comma-separated integers") from exc
    if any(telegram_id <= 0 for telegram_id in result):
        raise ValueError("ADMIN_TELEGRAM_IDS must contain positive Telegram IDs")
    return result


# Browser clients authenticate with Telegram initData. This allowlist remains
# server-side and must never be embedded in the MiniApp bundle.
ADMIN_TELEGRAM_IDS = _telegram_id_allowlist(os.getenv("ADMIN_TELEGRAM_IDS"))

# Public payment requisites returned only to authenticated MiniApp users when
# they create a deposit. Values must be configured by the deployment.
DEPOSIT_CARD_NUMBER = os.getenv("DEPOSIT_CARD_NUMBER")
DEPOSIT_CARD_HOLDER = os.getenv("DEPOSIT_CARD_HOLDER")
DEPOSIT_BANK_NAME = os.getenv("DEPOSIT_BANK_NAME")

S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_REGION = os.getenv("S3_REGION", "auto")
S3_PRESIGNED_URL_TTL_SECONDS = int(os.getenv("S3_PRESIGNED_URL_TTL_SECONDS", "300"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "LevelGroupBot").lstrip("@")
NEW_ORDERS_CHANNEL_ID = os.getenv("NEW_ORDERS_CHANNEL_ID")
TELEGRAM_API_BASE_URL = os.getenv("TELEGRAM_API_BASE_URL", "https://api.telegram.org")
COIN_MINIAPP_URL = (
    os.getenv("COIN_MINIAPP_URL")
    or os.getenv("MINIAPP_URL")
    or "https://miniapp-jocker7005.waw0.amvera.tech/"
)
TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS = int(os.getenv("TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS", "15"))
COIN_OTP_NOTIFICATION_STALE_SECONDS = int(os.getenv("COIN_OTP_NOTIFICATION_STALE_SECONDS", "300"))
RECEIPT_NOTIFICATION_MAX_ATTEMPTS = int(os.getenv("RECEIPT_NOTIFICATION_MAX_ATTEMPTS", "5"))
RECEIPT_NOTIFICATION_STALE_SECONDS = int(os.getenv("RECEIPT_NOTIFICATION_STALE_SECONDS", "300"))
WITHDRAW_NOTIFICATION_MAX_ATTEMPTS = int(os.getenv("WITHDRAW_NOTIFICATION_MAX_ATTEMPTS", "5"))
WITHDRAW_NOTIFICATION_STALE_SECONDS = int(os.getenv("WITHDRAW_NOTIFICATION_STALE_SECONDS", "300"))
if RECEIPT_NOTIFICATION_MAX_ATTEMPTS < 1 or RECEIPT_NOTIFICATION_STALE_SECONDS <= 0:
    raise ValueError("Invalid receipt notification configuration")
if WITHDRAW_NOTIFICATION_MAX_ATTEMPTS < 1 or WITHDRAW_NOTIFICATION_STALE_SECONDS <= 0:
    raise ValueError("Invalid withdraw notification configuration")
if COIN_OTP_NOTIFICATION_STALE_SECONDS <= 0:
    raise ValueError("Invalid Coin OTP notification stale timeout")
