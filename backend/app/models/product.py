from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.sql import func

from app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    title = Column(String(150), nullable=False)

    category = Column(String(50), nullable=False)
    # ANDROID_COINS, REGION_COINS, SPECIAL_PACK

    platform = Column(String(50), nullable=True)
    # android, ios, region

    region = Column(String(100), nullable=True)

    coins_amount = Column(Integer, nullable=False)

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
        CheckConstraint("coins_amount > 0", name="ck_products_coins_amount_positive"),
        CheckConstraint("price_uzs > 0", name="ck_products_price_positive"),
        Index(
            "uq_products_scope_coin_amount",
            func.upper(func.coalesce(platform, "")),
            func.upper(func.coalesce(region, "")),
            coins_amount,
            unique=True,
        ),
    )
