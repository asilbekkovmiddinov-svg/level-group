from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Index, Integer, Numeric, String, func, text
from sqlalchemy.sql import func

from app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    title = Column(String(150), nullable=False)

    product_type = Column(String(20), nullable=False, default="COIN", server_default="COIN")
    # COIN, PLAYER, MANAGER

    category = Column(String(50), nullable=False)
    # ANDROID_COINS, REGION_COINS, SPECIAL_PACK

    platform = Column(String(50), nullable=True)
    # android, ios, region

    region = Column(String(100), nullable=True)

    coins_amount = Column(Integer, nullable=True)

    price_uzs = Column(Numeric(18, 2), nullable=False)

    description = Column(String(255), nullable=True)

    order_index = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "(product_type = 'COIN' AND coins_amount > 0) OR "
            "(product_type IN ('PLAYER','MANAGER') AND coins_amount IS NULL)",
            name="ck_products_type_coins",
        ),
        CheckConstraint(
            "product_type IN ('COIN','PLAYER','MANAGER')",
            name="ck_products_product_type",
        ),
        CheckConstraint("price_uzs > 0", name="ck_products_price_positive"),
        Index(
            "uq_products_scope_coin_amount",
            func.upper(func.coalesce(platform, "")),
            func.upper(func.coalesce(region, "")),
            coins_amount,
            unique=True,
        ),
        Index(
            "uq_products_named_item",
            product_type,
            func.upper(title),
            unique=True,
            postgresql_where=text("product_type IN ('PLAYER','MANAGER')"),
            sqlite_where=text("product_type IN ('PLAYER','MANAGER')"),
        ),
    )
