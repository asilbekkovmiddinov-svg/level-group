from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.models.product import Product
from app.schemas.coin_promotion import CoinPromotionCreate, CoinPromotionResponse, CoinPromotionUpdate
from app.services import coin_promotion_admin as service


router = APIRouter(prefix="/admin/coin-promotions", tags=["Coin Promotions Admin"])


def response(db: Session, promotion) -> dict:
    product = db.get(Product, promotion.coin_package_id)
    return {
        "id": promotion.id,
        "coin_package_id": promotion.coin_package_id,
        "coin_package": {
            "id": product.id,
            "title": product.title,
            "category": product.category,
            "coin_amount": product.coins_amount,
            "price": float(product.price_uzs),
        },
        "title": promotion.title,
        "original_price": float(promotion.original_price),
        "promotion_price": float(promotion.promotion_price),
        "total_quantity": promotion.total_quantity,
        "reserved_quantity": promotion.reserved_quantity,
        "sold_quantity": promotion.sold_quantity,
        "remaining_quantity": promotion.remaining_quantity,
        "per_user_limit": promotion.per_user_limit,
        "status": promotion.status,
        "start_at": promotion.start_at,
        "end_at": promotion.end_at,
        "created_at": promotion.created_at,
        "updated_at": promotion.updated_at,
    }


@router.get("", response_model=list[CoinPromotionResponse])
def list_promotions(
    include_deleted: bool = True,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return [response(db, item) for item in service.list_all(db, include_deleted)]


@router.get("/{promotion_id}", response_model=CoinPromotionResponse)
def promotion_detail(
    promotion_id: int,
    include_deleted: bool = False,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return response(db, service.detail(db, promotion_id, include_deleted))


@router.post("", response_model=CoinPromotionResponse, status_code=201)
def create_promotion(
    data: CoinPromotionCreate,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return response(db, service.create(db, data))


@router.put("/{promotion_id}", response_model=CoinPromotionResponse)
def update_promotion(
    promotion_id: int,
    data: CoinPromotionUpdate,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return response(db, service.update(db, promotion_id, data))


def status_endpoint(target: str):
    def endpoint(
        promotion_id: int,
        _admin: TelegramUser = Depends(require_promotions_admin),
        db: Session = Depends(get_db),
    ):
        return response(db, service.change_status(db, promotion_id, target))

    return endpoint


for path, target in (("activate", "ACTIVE"), ("pause", "PAUSED"), ("deactivate", "DRAFT")):
    router.add_api_route(
        "/{promotion_id}/" + path,
        status_endpoint(target),
        methods=["POST"],
        response_model=CoinPromotionResponse,
    )


@router.delete("/{promotion_id}", response_model=CoinPromotionResponse)
def delete_promotion(
    promotion_id: int,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return response(db, service.soft_delete(db, promotion_id))


@router.post("/{promotion_id}/restore", response_model=CoinPromotionResponse)
def restore_promotion(
    promotion_id: int,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return response(db, service.restore(db, promotion_id))
