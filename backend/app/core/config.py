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

S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_REGION = os.getenv("S3_REGION", "auto")
S3_PRESIGNED_URL_TTL_SECONDS = int(os.getenv("S3_PRESIGNED_URL_TTL_SECONDS", "300"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_DEPOSIT_CHANNEL_ID = os.getenv("ADMIN_DEPOSIT_CHANNEL_ID")
TELEGRAM_API_BASE_URL = os.getenv("TELEGRAM_API_BASE_URL", "https://api.telegram.org")
TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS = int(os.getenv("TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS", "15"))
RECEIPT_NOTIFICATION_MAX_ATTEMPTS = int(os.getenv("RECEIPT_NOTIFICATION_MAX_ATTEMPTS", "5"))
RECEIPT_NOTIFICATION_STALE_SECONDS = int(os.getenv("RECEIPT_NOTIFICATION_STALE_SECONDS", "300"))
if RECEIPT_NOTIFICATION_MAX_ATTEMPTS < 1 or RECEIPT_NOTIFICATION_STALE_SECONDS <= 0:
    raise ValueError("Invalid receipt notification configuration")
