from sqlalchemy.orm import Session

from app.models.product import Product


ANDROID_DESCRIPTION = "Akkaunt ichiga kirib coin olib beriladi."

REGION_DESCRIPTION = (
    "Android va iPhone uchun region orqali limit yo'qotmasdan coin olib beriladi."
)


ANDROID_PRODUCTS = [
    (260, 35000),
    (300, 40000),
    (390, 55000),
    (550, 65000),
    (750, 90000),
    (1040, 120000),
    (1790, 205000),
    (2130, 235000),
    (2680, 305000),
    (3250, 345000),
    (4000, 435000),
    (5700, 555000),
    (7040, 725000),
    (9990, 1045000),
    (12800, 1185000),
]


REGION_PRODUCTS = [
    (578, 65000),
    (788, 95000),
    (1092, 130000),
    (2237, 245000),
    (2815, 310000),
    (3413, 365000),
    (4474, 495000),
    (5985, 595000),
    (13440, 1245000),
    (32200, 2795000),
]


def seed_products(db: Session):

    if db.query(Product).count() > 0:
        return

    order = 1

    for coins, price in ANDROID_PRODUCTS:
        db.add(
            Product(
                title=f"{coins} Coins",
                category="ANDROID_COINS",
                platform="android",
                region=None,
                coins_amount=coins,
                price_uzs=price,
                description=ANDROID_DESCRIPTION,
                order_index=order,
                is_active=True,
            )
        )
        order += 1

    order = 1

    for coins, price in REGION_PRODUCTS:
        db.add(
            Product(
                title=f"{coins} Coins",
                category="REGION_COINS",
                platform="region",
                region=None,
                coins_amount=coins,
                price_uzs=price,
                description=REGION_DESCRIPTION,
                order_index=order,
                is_active=True,
            )
        )
        order += 1

    db.commit()
