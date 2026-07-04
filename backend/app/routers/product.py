from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.product import (
    create_product,
    get_products,
    get_active_products,
    update_product
)
from app.schemas.product import ProductCreate, ProductUpdate

router = APIRouter(
    prefix="/products",
    tags=["Products"]
)


@router.post("/create")
def create_new_product(
    data: ProductCreate,
    db: Session = Depends(get_db)
):
    product = create_product(db, data)

    return {
        "message": "Product created",
        "product_id": product.id,
        "title": product.title,
        "price_uzs": float(product.price_uzs),
        "is_active": product.is_active
    }


@router.get("/all")
def all_products(db: Session = Depends(get_db)):
    return get_products(db)


@router.get("/active")
def active_products(db: Session = Depends(get_db)):
    return get_active_products(db)


@router.put("/update/{product_id}")
def update_existing_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db)
):
    product = update_product(db, product_id, data)

    if not product:
        return {
            "message": "Product not found"
        }

    return {
        "message": "Product updated",
        "product_id": product.id,
        "title": product.title,
        "price_uzs": float(product.price_uzs),
        "is_active": product.is_active
    }
