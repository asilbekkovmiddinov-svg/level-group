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
# balance operations.  It must never be exposed to the Mini App.
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
