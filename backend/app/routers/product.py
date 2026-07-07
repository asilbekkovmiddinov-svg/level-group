from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.product import (
    create_product,
    get_products,
    get_active_products,
    update_product,
)
from app.schemas.product import ProductCreate, ProductUpdate

router = APIRouter(
    prefix="/products",
    tags=["Products"],
)


def product_response(product):
    return {
        "id": product.id,
        "name": product.title,
        "title": product.title,
        "coin_amount": getattr(product, "coin_amount", 0),
        "price": float(product.price_uzs),
        "price_uzs": float(product.price_uzs),
        "is_active": product.is_active,
    }


@router.post("/create")
def create_new_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
):
    product = create_product(db, data)

    return {
        "success": True,
        "message": "Product created",
        "data": product_response(product),
    }


@router.get("/all")
def all_products(db: Session = Depends(get_db)):
    products = get_products(db)

    return {
        "success": True,
        "data": [product_response(product) for product in products],
    }


@router.get("/active")
def active_products(db: Session = Depends(get_db)):
    products = get_active_products(db)

    return {
        "success": True,
        "data": [product_response(product) for product in products],
    }


@router.put("/update/{product_id}")
def update_existing_product(
    product_id: int,
    data: ProductUpdate,
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
        "data": product_response(product),
    }
