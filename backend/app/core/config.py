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
SUPPORT_TELEGRAM_USERNAME = os.getenv("SUPPORT_TELEGRAM_USERNAME")
NEW_ORDERS_CHANNEL_ID = os.getenv("NEW_ORDERS_CHANNEL_ID")
ARENA_ADMIN_CHANNEL_ID = os.getenv("ARENA_ADMIN_CHANNEL_ID")
TELEGRAM_API_BASE_URL = os.getenv("TELEGRAM_API_BASE_URL", "https://api.telegram.org")
COIN_MINIAPP_URL = (
    os.getenv("COIN_MINIAPP_URL")
    or os.getenv("MINIAPP_URL")
    or "https://miniapp-jocker7005.waw0.amvera.tech/"
)
TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS = int(os.getenv("TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS", "15"))
COIN_OTP_NOTIFICATION_STALE_SECONDS = int(os.getenv("COIN_OTP_NOTIFICATION_STALE_SECONDS", "300"))
CAMPAIGN_WORKER_INTERVAL_SECONDS = float(os.getenv("CAMPAIGN_WORKER_INTERVAL_SECONDS", "30"))
CAMPAIGN_WORKER_ENABLED = os.getenv("CAMPAIGN_WORKER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
CAMPAIGN_DELIVERY_BATCH_SIZE = int(os.getenv("CAMPAIGN_DELIVERY_BATCH_SIZE", "100"))
CAMPAIGN_DELIVERY_RETRY_LIMIT = int(os.getenv("CAMPAIGN_DELIVERY_RETRY_LIMIT", "5"))
CAMPAIGN_DELIVERY_CLAIM_TTL_SECONDS = int(os.getenv("CAMPAIGN_DELIVERY_CLAIM_TTL_SECONDS", "300"))
COIN_PROMOTION_ORDER_TIMEOUT_SECONDS = int(os.getenv("COIN_PROMOTION_ORDER_TIMEOUT_SECONDS", "1800"))
COIN_PROMOTION_TIMEOUT_INTERVAL_SECONDS = float(os.getenv("COIN_PROMOTION_TIMEOUT_INTERVAL_SECONDS", "30"))
ARENA_TIMEOUT_INTERVAL_SECONDS = float(os.getenv("ARENA_TIMEOUT_INTERVAL_SECONDS", "30"))
PENALTY_DUEL_TIMEOUT_INTERVAL_SECONDS = float(
    os.getenv("PENALTY_DUEL_TIMEOUT_INTERVAL_SECONDS", "5")
)

def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
        raise ValueError(f"{name} must be a boolean")
    return normalized in {"1", "true", "yes", "on"}


# Temporary launch gate. Keep disabled by default until referrals reopen.
REFERRALS_ENABLED = _env_bool("REFERRALS_ENABLED", False)


ARENA_V3_ENABLED = _env_bool("ARENA_V3_ENABLED", True)
ARENA_V3_CREATE_ENABLED = _env_bool("ARENA_V3_CREATE_ENABLED", True)
ARENA_V3_AI_ENABLED = _env_bool("ARENA_V3_AI_ENABLED", False)
ARENA_V3_AI_MODEL = os.getenv("ARENA_V3_AI_MODEL", "gpt-5.4-nano").strip()
ARENA_V3_AI_INTERVAL_SECONDS = float(os.getenv("ARENA_V3_AI_INTERVAL_SECONDS", "5"))
ARENA_V3_AI_TIMEOUT_SECONDS = float(os.getenv("ARENA_V3_AI_TIMEOUT_SECONDS", "45"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ARENA_V3_SETTLEMENT_ENABLED = _env_bool("ARENA_V3_SETTLEMENT_ENABLED", False)
ARENA_V3_REFUND_ON_AI_FAILURE = _env_bool(
    "ARENA_V3_REFUND_ON_AI_FAILURE", False
)
ARENA_V3_NOTIFICATION_INTERVAL_SECONDS = float(
    os.getenv("ARENA_V3_NOTIFICATION_INTERVAL_SECONDS", "15")
)
ARENA_V4_REWARD_RELEASE_INTERVAL_SECONDS = float(
    os.getenv("ARENA_V4_REWARD_RELEASE_INTERVAL_SECONDS", "15")
)
ARENA_V3_NOTIFICATION_CLAIM_TTL_SECONDS = int(
    os.getenv("ARENA_V3_NOTIFICATION_CLAIM_TTL_SECONDS", "300")
)
ARENA_V3_NOTIFICATION_MAX_ATTEMPTS = int(
    os.getenv("ARENA_V3_NOTIFICATION_MAX_ATTEMPTS", "3")
)
ARENA_V3_ALLOWED_TELEGRAM_IDS = _telegram_id_allowlist(
    os.getenv("ARENA_V3_ALLOWED_TELEGRAM_IDS")
)
ARENA_V2_CREATE_ENABLED = _env_bool("ARENA_V2_CREATE_ENABLED", True)
ADSGRAM_REWARD_SECRET = os.getenv("ADSGRAM_REWARD_SECRET")
ADSGRAM_REWARD_SESSION_TTL_SECONDS = int(os.getenv("ADSGRAM_REWARD_SESSION_TTL_SECONDS", "300"))
MONETAG_POSTBACK_SECRET = os.getenv("MONETAG_POSTBACK_SECRET")
TADS_WEBHOOK_SECRET = os.getenv("TADS_WEBHOOK_SECRET")
TADS_WALL_RUSH_WIDGET_ID = os.getenv("TADS_WALL_RUSH_WIDGET_ID", "11416").strip()
TELEGA_REWARD_SECRET = os.getenv("TELEGA_REWARD_SECRET")
TELEGA_MINIAPP_TOKEN = os.getenv("TELEGA_MINIAPP_TOKEN")
TELEGA_REWARDED_AD_BLOCK_UUID = os.getenv(
    "TELEGA_REWARDED_AD_BLOCK_UUID", "626b9d82-89c5-4e08-b6d4-9fc8bdc2f486"
).strip()
ONCLICKA_REWARD_SECRET = os.getenv("ONCLICKA_REWARD_SECRET")
ONCLICKA_SPOT_ID = os.getenv("ONCLICKA_SPOT_ID", "6131849").strip()
MONETAG_REWARD_SESSION_TTL_SECONDS = int(os.getenv("MONETAG_REWARD_SESSION_TTL_SECONDS", "60"))
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
if CAMPAIGN_WORKER_INTERVAL_SECONDS <= 0:
    raise ValueError("CAMPAIGN_WORKER_INTERVAL_SECONDS must be positive")
if CAMPAIGN_DELIVERY_BATCH_SIZE < 1 or CAMPAIGN_DELIVERY_BATCH_SIZE > 1000:
    raise ValueError("CAMPAIGN_DELIVERY_BATCH_SIZE must be between 1 and 1000")
if CAMPAIGN_DELIVERY_RETRY_LIMIT < 1:
    raise ValueError("CAMPAIGN_DELIVERY_RETRY_LIMIT must be positive")
if CAMPAIGN_DELIVERY_CLAIM_TTL_SECONDS < 1:
    raise ValueError("CAMPAIGN_DELIVERY_CLAIM_TTL_SECONDS must be positive")
if COIN_PROMOTION_ORDER_TIMEOUT_SECONDS < 1 or COIN_PROMOTION_TIMEOUT_INTERVAL_SECONDS <= 0:
    raise ValueError("Invalid Coin Promotion timeout configuration")
if ARENA_TIMEOUT_INTERVAL_SECONDS <= 0:
    raise ValueError("ARENA_TIMEOUT_INTERVAL_SECONDS must be positive")
if PENALTY_DUEL_TIMEOUT_INTERVAL_SECONDS <= 0:
    raise ValueError("PENALTY_DUEL_TIMEOUT_INTERVAL_SECONDS must be positive")
if ARENA_V3_AI_INTERVAL_SECONDS <= 0 or ARENA_V3_AI_TIMEOUT_SECONDS <= 0:
    raise ValueError("Arena V3 AI timing settings must be positive")
if not ARENA_V3_AI_MODEL:
    raise ValueError("ARENA_V3_AI_MODEL must not be empty")
if (
    ARENA_V3_NOTIFICATION_INTERVAL_SECONDS <= 0
    or ARENA_V3_NOTIFICATION_CLAIM_TTL_SECONDS < 1
    or ARENA_V3_NOTIFICATION_MAX_ATTEMPTS < 1
):
    raise ValueError("Arena V3 notification settings are invalid")
if ARENA_V4_REWARD_RELEASE_INTERVAL_SECONDS <= 0:
    raise ValueError("Arena V4 reward release interval must be positive")
if ADSGRAM_REWARD_SESSION_TTL_SECONDS < 30:
    raise ValueError("ADSGRAM_REWARD_SESSION_TTL_SECONDS must be at least 30")
if MONETAG_REWARD_SESSION_TTL_SECONDS < 60:
    raise ValueError("MONETAG_REWARD_SESSION_TTL_SECONDS must be at least 60")
