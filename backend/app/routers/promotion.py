from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.routers.internal_wallet import require_internal_api_key
from app.schemas.promotion import (
    PromotionCreate,
    PromotionResponse,
    PromotionUpdate,
    PublicPromotionResponse,
)
from app.services import promotions


admin_router = APIRouter(
    prefix="/admin/promotions",
    tags=["Marketing CMS"],
    dependencies=[Depends(require_internal_api_key)],
)
public_router = APIRouter(prefix="/promotions", tags=["Promotions"])


def actor_id(
    x_admin_telegram_id: Annotated[int | None, Header()] = None,
) -> int | None:
    return x_admin_telegram_id


@admin_router.post("", response_model=PromotionResponse, status_code=201)
def create_promotion(
    data: PromotionCreate,
    actor: int | None = Depends(actor_id),
    db: Session = Depends(get_db),
):
    return promotions.create(db, data, actor)


@admin_router.patch("/{promotion_id}", response_model=PromotionResponse)
def update_promotion(
    promotion_id: int,
    data: PromotionUpdate,
    actor: int | None = Depends(actor_id),
    db: Session = Depends(get_db),
):
    return promotions.update(db, promotion_id, data, actor)


@admin_router.delete("/{promotion_id}", response_model=PromotionResponse)
def delete_promotion(
    promotion_id: int,
    actor: int | None = Depends(actor_id),
    db: Session = Depends(get_db),
):
    return promotions.soft_delete(db, promotion_id, actor)


@admin_router.post("/{promotion_id}/restore", response_model=PromotionResponse)
def restore_promotion(
    promotion_id: int,
    actor: int | None = Depends(actor_id),
    db: Session = Depends(get_db),
):
    return promotions.restore(db, promotion_id, actor)


def status_endpoint(target: str):
    def endpoint(
        promotion_id: int,
        actor: int | None = Depends(actor_id),
        db: Session = Depends(get_db),
    ):
        return promotions.change_status(db, promotion_id, target, actor)

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
    db: Session = Depends(get_db),
):
    return promotions.list_promotions(db, include_deleted)


@admin_router.get("/{promotion_id}", response_model=PromotionResponse)
def promotion_detail(
    promotion_id: int,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    return promotions.detail(db, promotion_id, include_deleted)


@public_router.get("/active", response_model=list[PublicPromotionResponse])
def active_promotions(
    _current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return promotions.public_active(db)
