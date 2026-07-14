from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


TASHKENT = ZoneInfo("Asia/Tashkent")
UTC = timezone.utc

ROOM_READY_TIMEOUT = timedelta(minutes=10)
EVIDENCE_TIMEOUT = timedelta(hours=2)
ADMIN_REVIEW_TIMEOUT = timedelta(hours=24)


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize DB/worker values; legacy naive values are treated as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def api_tashkent_to_utc(value: datetime) -> datetime:
    """Normalize public API time; a naive client value means Asia/Tashkent."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=TASHKENT)
    return value.astimezone(UTC)

