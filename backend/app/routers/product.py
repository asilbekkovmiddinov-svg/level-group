from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.product import (
    create_product,
    get_products,
    get_active_products,
    get_active_products_by_category,
    update_product,
)
from app.schemas.product import ProductCreate, ProductUpdate
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.routers.internal_wallet import require_internal_api_key
from app.services.coin_promotions import product_promotion

router = APIRouter(
    prefix="/products",
    tags=["Products"],
)


def product_response(product, db: Session | None = None):
    promotion = product_promotion(db, product.id) if db is not None else None
    return {
        "id": product.id,
        "name": product.title,
        "title": product.title,
        "category": product.category,
        "platform": product.platform,
        "region": product.region,
        "coin_amount": product.coins_amount,
        "coins_amount": product.coins_amount,
        "price": float(product.price_uzs),
        "price_uzs": float(product.price_uzs),
        "description": product.description,
        "order_index": product.order_index,
        "is_active": product.is_active,
        "original_price": promotion["original_price"] if promotion else float(product.price_uzs),
        "promotion_price": promotion["promotion_price"] if promotion else None,
        "remaining_quantity": promotion["remaining_quantity"] if promotion else None,
        "promotion_id": promotion["promotion_id"] if promotion else None,
    }


@router.post("/create")
def create_new_product(
    data: ProductCreate,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    product = create_product(db, data)

    return {
        "success": True,
        "message": "Product created",
        "data": product_response(product, db),
    }


@router.get("/all")
def all_products(
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    products = get_products(db)

    return {
        "success": True,
        "data": [product_response(product, db) for product in products],
    }


@router.get("/active")
def active_products(
    category: str | None = None,
    _current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    if category:
        products = get_active_products_by_category(
            db=db,
            category=category,
        )
    else:
        products = get_active_products(db)

    return {
        "success": True,
        "data": [product_response(product, db) for product in products],
    }


@router.put("/update/{product_id}")
def update_existing_product(
    product_id: int,
    data: ProductUpdate,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    product = update_product(db, product_id, data)

    if not product:
        return {
            "success": False,
            "message": "Product not found",
        }

    return {
        "success": True,
        "message": "Product updated",
        "data": product_response(product, db),
    }
