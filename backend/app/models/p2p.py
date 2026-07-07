from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    Numeric,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class P2POrder(Base):
    __tablename__ = "p2p_orders"

    id = Column(Integer, primary_key=True, index=True)

    owner_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True,
    )

    order_type = Column(
        String(10),
        nullable=False,
        index=True,
    )

    efc_amount = Column(
        Numeric(18, 4),
        nullable=False,
    )

    remaining_efc = Column(
        Numeric(18, 4),
        nullable=False,
    )

    price_uzs = Column(
        Numeric(18, 2),
        nullable=False,
    )

    min_trade_efc = Column(
        Numeric(18, 4),
        nullable=False,
    )

    response_minutes = Column(
        Integer,
        nullable=False,
        default=15,
    )

    locked_currency = Column(
        String(10),
        nullable=False,
    )

    locked_amount = Column(
        Numeric(18, 4),
        nullable=False,
        default=0,
    )

    status = Column(
        String(20),
        nullable=False,
        default="OPEN",
        index=True,
    )
        cancel_reason = Column(
        String(255),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    trades = relationship(
        "P2PTrade",
        back_populates="order",
        cascade="all, delete-orphan",
    )


class P2PTrade(Base):
    __tablename__ = "p2p_trades"

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(
        Integer,
        ForeignKey("p2p_orders.id"),
        nullable=False,
        index=True,
    )

    owner_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True,
    )

    requester_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True,
    )

    order_type = Column(
        String(10),
        nullable=False,
        index=True,
    )

    efc_amount = Column(
        Numeric(18, 4),
        nullable=False,
    )

    price_uzs = Column(
        Numeric(18, 2),
        nullable=False,
    )

    total_uzs = Column(
        Numeric(18, 2),
        nullable=False,
    )
    efc_fee = Column(
        Numeric(18, 4),
        nullable=False,
        default=0,
    )

    uzs_fee = Column(
        Numeric(18, 2),
        nullable=False,
        default=0,
    )

    owner_status = Column(
        String(20),
        nullable=False,
        default="PENDING",
    )

    requester_status = Column(
        String(20),
        nullable=False,
        default="PENDING",
    )

    status = Column(
        String(20),
        nullable=False,
        default="PENDING",
        index=True,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    owner_expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    requester_expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    timeout_stage = Column(
        String(30),
        nullable=True,
    )

    cancel_reason = Column(
        String(255),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    approved_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejected_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    timeout_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    order = relationship(
        "P2POrder",
        back_populates="trades",
    )
