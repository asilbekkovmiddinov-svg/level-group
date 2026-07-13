import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.core.telegram_auth import get_current_telegram_user
from app.routers import deposit_receipt
from app.services.object_storage import (
    StorageConfigurationError,
    StorageOperationError,
)


class FakeQuery:
    def __init__(self, deposit):
        self.deposit = deposit

    def filter(self, *_args):
        return self

    def first(self):
        return self.deposit


class FakeSession:
    def __init__(self, deposit):
        self.deposit = deposit

    def query(self, _model):
        return FakeQuery(self.deposit)


def receipt_file():
    return UploadFile(
        filename="receipt.jpg",
        file=BytesIO(b"\xff\xd8\xffreceipt"),
        headers=Headers({"content-type": "image/jpeg"}),
    )


def test_miniapp_evidence_url_restores_existing_receipt_handler():
    routes = {route.path: route for route in deposit_receipt.router.routes}

    legacy = routes["/deposits/{deposit_id}/receipt"]
    miniapp = routes["/deposit/{deposit_id}/evidence"]

    assert "POST" in legacy.methods
    assert "POST" in miniapp.methods
    assert legacy.endpoint is deposit_receipt.upload_deposit_receipt
    assert miniapp.endpoint is deposit_receipt.upload_deposit_receipt
    assert any(
        dependency.call is get_current_telegram_user
        for dependency in miniapp.dependant.dependencies
    )


def test_evidence_upload_hides_other_users_deposit(monkeypatch):
    deposit = SimpleNamespace(id=7, telegram_id=999, status="PENDING")
    uploaded = False

    def fail_if_uploaded(*_args, **_kwargs):
        nonlocal uploaded
        uploaded = True

    monkeypatch.setattr(deposit_receipt, "upload_object", fail_if_uploaded)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            deposit_receipt.upload_deposit_receipt(
                deposit_id=7,
                file=receipt_file(),
                current_user=SimpleNamespace(telegram_id=123),
                db=FakeSession(deposit),
            )
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Deposit not found"
    assert uploaded is False


def test_evidence_upload_keeps_pending_status_guard(monkeypatch):
    deposit = SimpleNamespace(id=7, telegram_id=123, status="APPROVED")
    uploaded = False

    def fail_if_uploaded(*_args, **_kwargs):
        nonlocal uploaded
        uploaded = True

    monkeypatch.setattr(deposit_receipt, "upload_object", fail_if_uploaded)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            deposit_receipt.upload_deposit_receipt(
                deposit_id=7,
                file=receipt_file(),
                current_user=SimpleNamespace(telegram_id=123),
                db=FakeSession(deposit),
            )
        )

    assert error.value.status_code == 400
    assert "pending" in error.value.detail
    assert uploaded is False


@pytest.mark.parametrize(
    ("storage_error", "expected_status", "expected_log"),
    [
        (
            StorageConfigurationError("missing S3_BUCKET_NAME"),
            503,
            "receipt storage configuration failed",
        ),
        (
            StorageOperationError("put_object failed"),
            502,
            "receipt object upload failed",
        ),
    ],
)
def test_evidence_upload_logs_storage_traceback(
    monkeypatch,
    caplog,
    storage_error,
    expected_status,
    expected_log,
):
    deposit = SimpleNamespace(
        id=7,
        telegram_id=123,
        status="PENDING",
        receipt_object_key=None,
    )

    def fail_upload(*_args, **_kwargs):
        raise storage_error

    monkeypatch.setattr(deposit_receipt, "upload_object", fail_upload)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            deposit_receipt.upload_deposit_receipt(
                deposit_id=7,
                file=receipt_file(),
                current_user=SimpleNamespace(telegram_id=123),
                db=FakeSession(deposit),
            )
        )

    assert error.value.status_code == expected_status
    records = [record for record in caplog.records if expected_log in record.message]
    assert len(records) == 1
    assert records[0].exc_info is not None
