import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.models.promotion import Promotion
from app.routers.promotion import promotion_response
from app.services.object_storage import (
    StorageConfigurationError,
    StorageOperationError,
    delete_object,
    upload_object,
)
from app.services.promotion_banners import (
    MAX_PROMOTION_BANNER_SIZE,
    validate_promotion_banner,
)


router = APIRouter(prefix="/admin/promotions", tags=["Marketing CMS"])
logger = logging.getLogger(__name__)


def locked_promotion(db: Session, promotion_id: int) -> Promotion:
    promotion = (
        db.query(Promotion)
        .filter(Promotion.id == promotion_id, Promotion.deleted_at.is_(None))
        .with_for_update()
        .first()
    )
    if promotion is None:
        raise HTTPException(404, "Promotion not found")
    return promotion


@router.post("/{promotion_id}/banner")
async def upload_promotion_banner(
    promotion_id: int,
    file: UploadFile = File(...),
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    content = await file.read(MAX_PROMOTION_BANNER_SIZE + 1)
    extension, content_type = validate_promotion_banner(file, content)
    promotion = locked_promotion(db, promotion_id)
    old_key = promotion.banner_object_key
    new_key = f"promotions/{promotion.id}/banners/{uuid4()}.{extension}"
    try:
        await run_in_threadpool(upload_object, new_key, content, content_type)
    except StorageConfigurationError as error:
        raise HTTPException(503, "Banner storage is not configured") from error
    except StorageOperationError as error:
        raise HTTPException(502, "Banner upload failed") from error

    try:
        promotion.banner_url = None
        promotion.banner_object_key = new_key
        promotion.banner_content_type = content_type
        promotion.banner_size = len(content)
        promotion.banner_updated_at = datetime.now(timezone.utc)
        promotion.updated_by = admin.telegram_id
        db.commit()
        db.refresh(promotion)
    except Exception as error:
        db.rollback()
        try:
            await run_in_threadpool(delete_object, new_key)
        except Exception:
            logger.exception("new promotion banner cleanup failed", extra={"promotion_id": promotion_id})
        raise HTTPException(500, "Banner update failed") from error

    if old_key and old_key != new_key:
        try:
            await run_in_threadpool(delete_object, old_key)
        except Exception:
            logger.exception("old promotion banner cleanup failed", extra={"promotion_id": promotion_id})
    return promotion_response(promotion)


@router.delete("/{promotion_id}/banner")
async def delete_promotion_banner(
    promotion_id: int,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    promotion = locked_promotion(db, promotion_id)
    object_key = promotion.banner_object_key
    if object_key:
        try:
            await run_in_threadpool(delete_object, object_key)
        except StorageConfigurationError as error:
            raise HTTPException(503, "Banner storage is not configured") from error
        except StorageOperationError as error:
            raise HTTPException(502, "Banner delete failed") from error
    promotion.banner_url = None
    promotion.banner_object_key = None
    promotion.banner_content_type = None
    promotion.banner_size = None
    promotion.banner_updated_at = datetime.now(timezone.utc)
    promotion.updated_by = admin.telegram_id
    db.commit()
    db.refresh(promotion)
    return promotion_response(promotion)
