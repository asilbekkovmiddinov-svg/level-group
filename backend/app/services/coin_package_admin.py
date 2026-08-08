from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.seed_products import ANDROID_DESCRIPTION, REGION_DESCRIPTION
from app.models.product import Product
from app.schemas.product import CoinPackageCreate, CoinPackageScope, CoinPackageUpdate


def package_scope(product: Product) -> CoinPackageScope:
    platform = str(product.platform or "").strip().upper()
    region = str(product.region or "").strip().upper()
    if platform == "ANDROID" or product.category == "ANDROID_COINS":
        return CoinPackageScope.ANDROID
    if region in {"JAPAN", "TURKEY"}:
        return CoinPackageScope(region)
    return CoinPackageScope.ALL


def _storage(scope: CoinPackageScope) -> dict:
    if scope == CoinPackageScope.ANDROID:
        return {
            "category": "ANDROID_COINS",
            "platform": "ANDROID",
            "region": "ALL",
            "description": ANDROID_DESCRIPTION,
        }
    return {
        "category": "REGION_COINS",
        "platform": "ALL",
        "region": scope.value,
        "description": REGION_DESCRIPTION,
    }


def _duplicate(db: Session, scope: CoinPackageScope, coin_amount: int, exclude_id: int | None = None):
    query = db.query(Product).with_for_update()
    if exclude_id is not None:
        query = query.filter(Product.id != exclude_id)
    for product in query.all():
        if package_scope(product) == scope and product.coins_amount == coin_amount:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Coin package already exists for this platform/region and amount",
            )


def _save(db: Session, product: Product) -> Product:
    try:
        db.add(product)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Coin package already exists") from error
    db.refresh(product)
    return product


def list_packages(db: Session, active_only: bool = False) -> list[Product]:
    query = db.query(Product)
    if active_only:
        query = query.filter(Product.is_active.is_(True))
    return query.order_by(Product.is_active.desc(), Product.coins_amount.asc(), Product.id.asc()).all()


def create(db: Session, data: CoinPackageCreate) -> Product:
    _duplicate(db, data.scope, data.coin_amount)
    storage = _storage(data.scope)
    product = Product(
        title=f"{data.coin_amount} Coins",
        coins_amount=data.coin_amount,
        price_uzs=data.price_uzs,
        is_active=data.is_active,
        order_index=data.coin_amount,
        **storage,
    )
    return _save(db, product)


def update(db: Session, product_id: int, data: CoinPackageUpdate) -> Product:
    product = db.query(Product).filter(Product.id == product_id).with_for_update().one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Coin package not found")
    _duplicate(db, data.scope, data.coin_amount, exclude_id=product_id)
    storage = _storage(data.scope)
    product.title = f"{data.coin_amount} Coins"
    product.coins_amount = data.coin_amount
    product.price_uzs = data.price_uzs
    product.is_active = data.is_active
    product.order_index = data.coin_amount
    for key, value in storage.items():
        setattr(product, key, value)
    return _save(db, product)


def set_active(db: Session, product_id: int, active: bool) -> Product:
    product = db.query(Product).filter(Product.id == product_id).with_for_update().one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Coin package not found")
    product.is_active = active
    return _save(db, product)
