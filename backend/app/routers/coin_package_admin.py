from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.schemas.product import CoinPackageAdminResponse, CoinPackageCreate, CoinPackageUpdate
from app.services import coin_package_admin as service


router = APIRouter(prefix="/admin/coin-packages", tags=["Coin Packages Admin"])


def response(product) -> dict:
    return {
        "id": product.id,
        "title": product.title,
        "category": product.category,
        "platform": product.platform,
        "region": product.region,
        "scope": service.package_scope(product).value,
        "product_type": service.item_type(product).value,
        "name": product.title if service.item_type(product).value != "COIN" else None,
        "coin_amount": product.coins_amount,
        "price_uzs": float(product.price_uzs),
        "is_active": bool(product.is_active),
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }


@router.get("", response_model=list[CoinPackageAdminResponse])
def list_packages(
    active_only: bool = False,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return [response(item) for item in service.list_packages(db, active_only)]


@router.post("", response_model=CoinPackageAdminResponse, status_code=201)
def create_package(
    data: CoinPackageCreate,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return response(service.create(db, data))


@router.put("/{product_id}", response_model=CoinPackageAdminResponse)
def update_package(
    product_id: int,
    data: CoinPackageUpdate,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return response(service.update(db, product_id, data))


def active_endpoint(active: bool):
    def endpoint(
        product_id: int,
        _admin: TelegramUser = Depends(require_promotions_admin),
        db: Session = Depends(get_db),
    ):
        return response(service.set_active(db, product_id, active))
    return endpoint


router.add_api_route("/{product_id}/activate", active_endpoint(True), methods=["POST"], response_model=CoinPackageAdminResponse)
router.add_api_route("/{product_id}/deactivate", active_endpoint(False), methods=["POST"], response_model=CoinPackageAdminResponse)
