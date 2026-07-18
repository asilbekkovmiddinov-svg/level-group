from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.schemas.promotion import (
    PromotionCreate,
    PromotionResponse,
    PromotionUpdate,
    PublicPromotionResponse,
)
from app.services import promotions
from app.services.object_storage import generate_presigned_get_url


admin_router = APIRouter(
    prefix="/admin/promotions",
    tags=["Marketing CMS"],
)
public_router = APIRouter(prefix="/promotions", tags=["Promotions"])


def promotion_response(promotion, public: bool = False) -> dict:
    schema = PublicPromotionResponse if public else PromotionResponse
    data = schema.model_validate(promotion).model_dump()
    object_key = getattr(promotion, "banner_object_key", None)
    if object_key:
        data["banner_url"] = generate_presigned_get_url(object_key)
    if not public:
        data["banner_uploaded"] = bool(object_key)
    return data


@admin_router.post("", response_model=PromotionResponse, status_code=201)
def create_promotion(
    data: PromotionCreate,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return promotion_response(promotions.create(db, data, admin.telegram_id))


@admin_router.patch("/{promotion_id}", response_model=PromotionResponse)
def update_promotion(
    promotion_id: int,
    data: PromotionUpdate,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return promotion_response(promotions.update(db, promotion_id, data, admin.telegram_id))


@admin_router.delete("/{promotion_id}", response_model=PromotionResponse)
def delete_promotion(
    promotion_id: int,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return promotion_response(promotions.soft_delete(db, promotion_id, admin.telegram_id))


@admin_router.post("/{promotion_id}/restore", response_model=PromotionResponse)
def restore_promotion(
    promotion_id: int,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return promotion_response(promotions.restore(db, promotion_id, admin.telegram_id))


def status_endpoint(target: str):
    def endpoint(
        promotion_id: int,
        admin: TelegramUser = Depends(require_promotions_admin),
        db: Session = Depends(get_db),
    ):
        return promotion_response(promotions.change_status(db, promotion_id, target, admin.telegram_id))

    return endpoint


admin_router.add_api_route(
    "/{promotion_id}/pause",
    status_endpoint("PAUSED"),
    methods=["POST"],
    response_model=PromotionResponse,
)
admin_router.add_api_route(
    "/{promotion_id}/activate",
    status_endpoint("ACTIVE"),
    methods=["POST"],
    response_model=PromotionResponse,
)
admin_router.add_api_route(
    "/{promotion_id}/deactivate",
    status_endpoint("DRAFT"),
    methods=["POST"],
    response_model=PromotionResponse,
)


@admin_router.get("", response_model=list[PromotionResponse])
def list_promotions(
    include_deleted: bool = False,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return [promotion_response(item) for item in promotions.list_promotions(db, include_deleted)]


@admin_router.get("/{promotion_id}", response_model=PromotionResponse)
def promotion_detail(
    promotion_id: int,
    include_deleted: bool = False,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return promotion_response(promotions.detail(db, promotion_id, include_deleted))


@public_router.get("/active", response_model=list[PublicPromotionResponse])
def active_promotions(
    _current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return [promotion_response(item, public=True) for item in promotions.public_active(db)]
