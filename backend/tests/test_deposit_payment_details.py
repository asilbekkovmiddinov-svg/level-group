import pytest
from fastapi import HTTPException

from app.routers import deposit as deposit_router


class FakeDeposit:
    id = 41
    telegram_id = 998877
    amount = 25000
    status = "PENDING"
    receipt_object_key = None
    receipt_content_type = None
    receipt_size = None
    receipt_uploaded_at = None


def configure_payment_details(monkeypatch):
    monkeypatch.setattr(deposit_router, "DEPOSIT_CARD_NUMBER", "8600 1111 2222 3333")
    monkeypatch.setattr(deposit_router, "DEPOSIT_CARD_HOLDER", "LEVEL GROUP")
    monkeypatch.setattr(deposit_router, "DEPOSIT_BANK_NAME", "Test Bank")


def test_deposit_create_response_matches_premium_miniapp_contract(monkeypatch):
    configure_payment_details(monkeypatch)

    response = deposit_router.deposit_create_response(FakeDeposit())

    assert response["deposit_id"] == 41
    assert response["status"] == "PENDING"
    assert response["amount"] == 25000.0
    assert response["card_number"] == "8600 1111 2222 3333"
    assert response["card_holder"] == "LEVEL GROUP"
    assert response["bank_name"] == "Test Bank"
    assert response["payment_details"] == {
        "card_number": "8600 1111 2222 3333",
        "card_holder": "LEVEL GROUP",
        "bank_name": "Test Bank",
    }
    assert "bank_links" not in response


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("DEPOSIT_CARD_NUMBER", None),
        ("DEPOSIT_CARD_HOLDER", ""),
        ("DEPOSIT_BANK_NAME", "   "),
    ],
)
def test_deposit_create_rejects_incomplete_payment_configuration(
    monkeypatch,
    field,
    value,
):
    configure_payment_details(monkeypatch)
    monkeypatch.setattr(deposit_router, field, value)

    with pytest.raises(HTTPException) as error:
        deposit_router.deposit_create_response(FakeDeposit())

    assert error.value.status_code == 503
    assert error.value.detail == "Deposit payment details are not configured"
