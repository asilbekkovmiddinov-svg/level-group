from sqlalchemy import Column, Integer, String, Numeric, DateTime
from sqlalchemy.sql import func

from app.core.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    telegram_id = Column(Integer, nullable=False, index=True)

    product_id = Column(Integer, nullable=False)

    product_title = Column(String(150), nullable=False)

    coins_amount = Column(Integer, nullable=False)

    price_uzs = Column(Numeric(18, 2), nullable=False)

    status = Column(
        String(30),
        default="PENDING"
    )
    # PENDING
    # PROCESSING
    # COMPLETED
    # CANCELLED

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
