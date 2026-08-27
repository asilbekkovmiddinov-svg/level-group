from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class ShopSettings(Base):
    __tablename__ = "shop_settings"

    id = Column(String(32), primary_key=True, default="default")
    efc_price_uzs = Column(Numeric(18, 2), nullable=False)
    ticket_price_efc = Column(Numeric(18, 2), nullable=False)
    updated_by = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ShopPurchase(Base):
    __tablename__ = "shop_purchases"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_shop_purchases_idempotency"),
        CheckConstraint(
            "purchase_type IN ('EFC', 'ARENA_TICKET')",
            name="ck_shop_purchases_type",
        ),
        CheckConstraint(
            "(purchase_type = 'EFC' AND efc_amount > 0 AND ticket_quantity IS NULL "
            "AND uzs_cost > 0 AND efc_cost IS NULL) OR "
            "(purchase_type = 'ARENA_TICKET' AND ticket_quantity > 0 "
            "AND efc_cost > 0 AND efc_amount IS NULL AND uzs_cost IS NULL)",
            name="ck_shop_purchases_payload",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True,
    )
    idempotency_key = Column(String(128), nullable=False)
    purchase_type = Column(String(24), nullable=False, index=True)
    efc_amount = Column(Numeric(18, 2), nullable=True)
    ticket_quantity = Column(Integer, nullable=True)
    uzs_cost = Column(Numeric(18, 2), nullable=True)
    efc_cost = Column(Numeric(18, 2), nullable=True)
    efc_price_uzs = Column(Numeric(18, 2), nullable=True)
    ticket_price_efc = Column(Numeric(18, 2), nullable=True)
    status = Column(String(20), nullable=False, default="COMPLETED")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
