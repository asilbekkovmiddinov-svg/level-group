from datetime import datetime, timezone
from zoneinfo import ZoneInfo


TASHKENT_TIMEZONE = ZoneInfo("Asia/Tashkent")
TELEGRAM_DATETIME_FORMAT = "%d.%m.%Y %H:%M:%S"


def format_tashkent_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(TASHKENT_TIMEZONE).strftime(TELEGRAM_DATETIME_FORMAT)
