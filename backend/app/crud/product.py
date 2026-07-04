from sqlalchemy.orm import Session

from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate


def create_product(db: Session, data: ProductCreate):
    product = Product(
        title=data.title,
        category=data.category,
        platform=data.platform,
        region=data.region,
        coins_amount=data.coins_amount,
        price_uzs=data.price_uzs,
        is_active=True
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    return product


def get_products(db: Session):
    return db.query(Product).order_by(
        Product.id.desc()
    ).all()


def get_active_products(db: Session):
    return db.query(Product).filter(
        Product.is_active == True
    ).order_by(Product.id.desc()).all()


def update_product(db: Session, product_id: int, data: ProductUpdate):
    product = db.query(Product).filter(
        Product.id == product_id
    ).first()

    if not product:
        return None

    update_data = data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)

    return product
