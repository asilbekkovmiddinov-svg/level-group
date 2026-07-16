from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    BigInteger,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "telegram_id",
            "idempotency_key",
            name="uq_order_user_idempotency",
        ),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    telegram_id = Column(BigInteger, nullable=False, index=True)

    product_id = Column(Integer, nullable=False)

    product_title = Column(String(150), nullable=False)

    coins_amount = Column(Integer, nullable=False)

    price_uzs = Column(Numeric(18, 2), nullable=False)

    region = Column(String(100), nullable=True)

    idempotency_key = Column(String(128), nullable=True)
    request_fingerprint = Column(String(64), nullable=True)

    status = Column(String(30), default="PENDING")
    # PENDING, CLAIMED, COMPLETED, REJECTED, CANCELLED

    claimed_by = Column(BigInteger, nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)

    completed_by = Column(BigInteger, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    rejected_by = Column(BigInteger, nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)

    reject_reason = Column(String(255), nullable=True)

    processing_seconds = Column(Integer, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
