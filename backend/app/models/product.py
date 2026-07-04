from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime
from sqlalchemy.sql import func

from app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    title = Column(String(150), nullable=False)

    category = Column(String(50), nullable=False)
    # ANDROID_COINS, REGION_COINS, IPHONE_COINS, SPECIAL_PACK

    platform = Column(String(50), nullable=True)
    # android, iphone, region

    region = Column(String(100), nullable=True)

    coins_amount = Column(Integer, nullable=False)

    price_uzs = Column(Numeric(18, 2), nullable=False)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
