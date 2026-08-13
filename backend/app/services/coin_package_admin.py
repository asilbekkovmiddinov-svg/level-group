from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.seed_products import ANDROID_DESCRIPTION, REGION_DESCRIPTION
from app.models.product import Product
from app.schemas.product import CoinPackageCreate, CoinPackageScope, CoinPackageUpdate, ProductType


NAMED_PRODUCT_STORAGE = {
    ProductType.PLAYER: {
        "category": "PLAYERS",
        "platform": "ALL",
        "region": "ALL",
        "description": "eFootball o‘yinchisi",
    },
    ProductType.MANAGER: {
        "category": "MANAGERS",
        "platform": "ALL",
        "region": "ALL",
        "description": "eFootball murabbiyi",
    },
}


def item_type(product: Product) -> ProductType:
    value = str(getattr(product, "product_type", None) or "").strip().upper()
    if value in ProductType._value2member_map_:
        return ProductType(value)
    if product.category == "PLAYERS":
        return ProductType.PLAYER
    if product.category == "MANAGERS":
        return ProductType.MANAGER
    return ProductType.COIN


def package_scope(product: Product) -> CoinPackageScope:
    if item_type(product) != ProductType.COIN:
        return CoinPackageScope.ALL
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


def _product_storage(product_type: ProductType, scope: CoinPackageScope) -> dict:
    if product_type == ProductType.COIN:
        return _storage(scope)
    return NAMED_PRODUCT_STORAGE[product_type].copy()


def _duplicate(
    db: Session,
    product_type: ProductType,
    scope: CoinPackageScope,
    coin_amount: int | None,
    name: str | None,
    exclude_id: int | None = None,
):
    query = db.query(Product).with_for_update()
    if exclude_id is not None:
        query = query.filter(Product.id != exclude_id)
    for product in query.all():
        if item_type(product) != product_type:
            continue
        duplicate_coin = (
            product_type == ProductType.COIN
            and package_scope(product) == scope
            and product.coins_amount == coin_amount
        )
        duplicate_name = (
            product_type != ProductType.COIN
            and str(product.title).strip().casefold() == str(name).strip().casefold()
        )
        if duplicate_coin or duplicate_name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Product already exists",
            )


def _save(db: Session, product: Product) -> Product:
    try:
        db.add(product)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Product already exists") from error
    db.refresh(product)
    return product


def list_packages(db: Session, active_only: bool = False) -> list[Product]:
    query = db.query(Product)
    if active_only:
        query = query.filter(Product.is_active.is_(True))
    return query.order_by(
        Product.is_active.desc(),
        Product.product_type.asc(),
        Product.coins_amount.asc(),
        Product.title.asc(),
        Product.id.asc(),
    ).all()


def create(db: Session, data: CoinPackageCreate) -> Product:
    _duplicate(db, data.product_type, data.scope, data.coin_amount, data.name)
    storage = _product_storage(data.product_type, data.scope)
    title = f"{data.coin_amount} Coins" if data.product_type == ProductType.COIN else data.name
    product = Product(
        title=title,
        product_type=data.product_type.value,
        coins_amount=data.coin_amount,
        price_uzs=data.price_uzs,
        is_active=data.is_active,
        order_index=data.coin_amount or 0,
        **storage,
    )
    return _save(db, product)


def update(db: Session, product_id: int, data: CoinPackageUpdate) -> Product:
    product = db.query(Product).filter(Product.id == product_id).with_for_update().one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if item_type(product) != data.product_type:
        raise HTTPException(status_code=422, detail="Product type cannot be changed")
    _duplicate(
        db, data.product_type, data.scope, data.coin_amount, data.name,
        exclude_id=product_id,
    )
    storage = _product_storage(data.product_type, data.scope)
    product.title = f"{data.coin_amount} Coins" if data.product_type == ProductType.COIN else data.name
    product.product_type = data.product_type.value
    product.coins_amount = data.coin_amount
    product.price_uzs = data.price_uzs
    product.is_active = data.is_active
    product.order_index = data.coin_amount
    if data.coin_amount is None:
        product.order_index = 0
    for key, value in storage.items():
        setattr(product, key, value)
    return _save(db, product)


def set_active(db: Session, product_id: int, active: bool) -> Product:
    product = db.query(Product).filter(Product.id == product_id).with_for_update().one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = active
    return _save(db, product)
