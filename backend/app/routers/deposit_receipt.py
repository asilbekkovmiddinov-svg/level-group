import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.models.deposit import Deposit
from app.services.object_storage import (
    StorageConfigurationError,
    StorageOperationError,
    delete_object,
    upload_object,
)
from app.services.deposit_notifications import send_deposit_receipt_notification

router = APIRouter(tags=["Deposits"])
logger = logging.getLogger(__name__)
MAX_RECEIPT_SIZE = 5 * 1024 * 1024
SIGNATURES = {"jpg": (b"\xff\xd8\xff", "image/jpeg"), "jpeg": (b"\xff\xd8\xff", "image/jpeg"), "png": (b"\x89PNG\r\n\x1a\n", "image/png"), "webp": (b"RIFF", "image/webp")}

def receipt_metadata(deposit):
    return {"receipt_uploaded": True, "receipt_content_type": deposit.receipt_content_type, "receipt_size": deposit.receipt_size, "receipt_uploaded_at": deposit.receipt_uploaded_at}

def validate_receipt(upload: UploadFile, content: bytes):
    ext = Path(upload.filename or "").suffix.lower().lstrip(".")
    if ext not in SIGNATURES or len(content) > MAX_RECEIPT_SIZE or not content:
        raise HTTPException(400, "Invalid receipt file")
    signature, content_type = SIGNATURES[ext]
    valid = content.startswith(signature) and (ext != "webp" or content[8:12] == b"WEBP")
    if not valid or upload.content_type != content_type:
        raise HTTPException(400, "Invalid receipt image")
    return ext, content_type

@router.post("/deposits/{deposit_id}/receipt")
@router.post("/deposit/{deposit_id}/evidence")
async def upload_deposit_receipt(deposit_id: int, file: UploadFile = File(...), current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    try:
        content = await file.read(MAX_RECEIPT_SIZE + 1)
    except Exception as error:
        logger.exception(
            "receipt file read failed",
            extra={"deposit_id": deposit_id},
        )
        raise HTTPException(500, "Receipt file read failed") from error
    ext, content_type = validate_receipt(file, content)
    try:
        deposit = db.query(Deposit).filter(Deposit.id == deposit_id).first()
    except Exception as error:
        logger.exception(
            "receipt deposit lookup failed",
            extra={"deposit_id": deposit_id},
        )
        raise HTTPException(500, "Receipt lookup failed") from error
    if not deposit or deposit.telegram_id != current_user.telegram_id:
        raise HTTPException(404, "Deposit not found")
    if deposit.status != "PENDING":
        raise HTTPException(400, "Receipt can only be changed while deposit is pending")
    new_key = f"receipts/deposits/{deposit.id}/{uuid4()}.{ext}"
    old_key = deposit.receipt_object_key
    try:
        upload_object(new_key, content, content_type)
    except StorageConfigurationError as error:
        logger.exception(
            "receipt storage configuration failed",
            extra={"deposit_id": deposit.id},
        )
        raise HTTPException(503, "Receipt storage is not configured") from error
    except StorageOperationError as error:
        logger.exception(
            "receipt object upload failed",
            extra={"deposit_id": deposit.id},
        )
        raise HTTPException(502, "Receipt storage upload failed") from error
    try:
        deposit.receipt_object_key = new_key; deposit.receipt_content_type = content_type; deposit.receipt_size = len(content); deposit.receipt_uploaded_at = datetime.now(timezone.utc); deposit.receipt_notification_status = "PENDING"; deposit.receipt_notification_attempts = 0; deposit.receipt_notification_sent_at = None; deposit.receipt_notification_message_id = None; deposit.receipt_notification_last_error = None; deposit.receipt_notification_last_attempt_at = None
        db.commit(); db.refresh(deposit)
    except Exception as error:
        db.rollback()
        logger.exception(
            "receipt database update failed",
            extra={"deposit_id": deposit.id},
        )
        try:
            delete_object(new_key)
        except (StorageConfigurationError, StorageOperationError):
            logger.exception(
                "receipt object cleanup failed after database error",
                extra={"deposit_id": deposit.id},
            )
        raise HTTPException(500, "Receipt update failed") from error
    if old_key:
        try:
            delete_object(old_key)
        except (StorageConfigurationError, StorageOperationError):
            logger.exception(
                "previous receipt object cleanup failed",
                extra={"deposit_id": deposit.id},
            )
    try:
        notification = send_deposit_receipt_notification(db, deposit.id)
        notification_status = notification.status
    except Exception:
        logger.exception(
            "receipt notification did not start",
            extra={"deposit_id": deposit.id},
        )
        notification_status = deposit.receipt_notification_status
    return {**receipt_metadata(deposit), "notification_status": notification_status}
