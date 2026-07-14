from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.timezone import format_tashkent_datetime
from app.routers.deposit import deposit_response
from app.routers.withdraw import withdraw_response
from app.services.deposit_notifications import _caption


UTC_TIME = datetime(2026, 7, 14, 10, 30, 45, tzinfo=timezone.utc)
LOCAL_TIME = "14.07.2026 15:30:45"


def test_formatter_converts_utc_to_tashkent_without_iso_offset():
    assert format_tashkent_datetime(UTC_TIME) == LOCAL_TIME
    assert "+00:00" not in format_tashkent_datetime(UTC_TIME)


def test_deposit_receipt_caption_uses_tashkent_times():
    deposit = SimpleNamespace(
        id=7,
        telegram_id=42,
        amount=25000,
        status="PENDING",
        created_at=UTC_TIME,
        receipt_uploaded_at=UTC_TIME,
    )

    caption = _caption(deposit, None)

    assert caption.count(LOCAL_TIME) == 2
    assert "+00:00" not in caption


def test_deposit_response_formats_all_lifecycle_times():
    deposit = SimpleNamespace(
        id=7,
        telegram_id=42,
        amount=25000,
        status="APPROVED",
        receipt_object_key="receipt",
        receipt_content_type="image/jpeg",
        receipt_size=100,
        created_at=UTC_TIME,
        receipt_uploaded_at=UTC_TIME,
        approved_at=UTC_TIME,
        rejected_at=None,
        processing_seconds=75,
    )

    response = deposit_response(deposit)

    assert response["created_at"] == LOCAL_TIME
    assert response["receipt_at"] == LOCAL_TIME
    assert response["approved_at"] == LOCAL_TIME
    assert response["rejected_at"] is None
    assert response["processing_seconds"] == 75


def test_withdraw_response_formats_all_lifecycle_times():
    withdraw = SimpleNamespace(
        id=8,
        telegram_id=42,
        amount=25000,
        card_number="8600",
        card_holder="LEVEL GROUP",
        bank_name="Bank",
        status="REJECTED",
        created_at=UTC_TIME,
        claimed_by=11,
        claimed_at=UTC_TIME,
        approved_by=None,
        approved_at=None,
        rejected_by=11,
        rejected_at=UTC_TIME,
        reject_reason="Receipt mismatch",
        processing_seconds=90,
    )

    response = withdraw_response(withdraw)

    assert response["created_at"] == LOCAL_TIME
    assert response["claimed_at"] == LOCAL_TIME
    assert response["approved_at"] is None
    assert response["rejected_at"] == LOCAL_TIME
    assert response["processing_seconds"] == 90
