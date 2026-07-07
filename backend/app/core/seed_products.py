from sqlalchemy.orm import Session

from app.models.product import Product


ANDROID_DESCRIPTION = "Akkaunt ichiga kirib coin olib beriladi."
REGION_DESCRIPTION = "Android va iPhone uchun limit yo'qotmasdan coin olib beriladi."

ANDROID_PRODUCTS = [
    (260, 35000), (300, 40000), (390, 55000), (550, 65000),
    (750, 90000), (1040, 120000), (1790, 205000), (2130, 235000),
    (2680, 305000), (3250, 345000), (4000, 435000),
    (5700, 555000), (7040, 725000), (9990, 1045000),
    (12800, 1185000),
]

REGION_PRODUCTS = [
    (578, 65000), (788, 95000), (1092, 130000), (2237, 245000),
    (2815, 310000), (3413, 365000), (4474, 495000),
    (5985, 595000), (13440, 1245000), (32200, 2795000),
]


def upsert_product(
    db: Session,
    category: str,
    platform: str,
    coins: int,
    price: int,
    description: str,
    order_index: int,
):
    product = (
        db.query(Product)
        .filter(
            Product.category == category,
            Product.coins_amount == coins,
        )
        .first()
    )

    if product:
        product.title = f"{coins} Coins"
        product.platform = platform
        product.region = None
        product.price_uzs = price
        product.description = description
        product.order_index = order_index
        product.is_active = True
        return

    db.add(
        Product(
            title=f"{coins} Coins",
            category=category,
            platform=platform,
            region=None,
            coins_amount=coins,
            price_uzs=price,
            description=description,
            order_index=order_index,
            is_active=True,
        )
    )


def seed_products(db: Session):
    for index, (coins, price) in enumerate(ANDROID_PRODUCTS, start=1):
        upsert_product(
            db=db,
            category="ANDROID_COINS",
            platform="android",
            coins=coins,
            price=price,
            description=ANDROID_DESCRIPTION,
            order_index=index,
        )

    for index, (coins, price) in enumerate(REGION_PRODUCTS, start=1):
        upsert_product(
            db=db,
            category="REGION_COINS",
            platform="region",
            coins=coins,
            price=price,
            description=REGION_DESCRIPTION,
            order_index=index,
        )

    db.commit()
