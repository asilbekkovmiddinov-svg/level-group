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

from app.core.database import Base


class P2POrder(Base):
    __tablename__ = "p2p_orders"

    id = Column(Integer, primary_key=True, index=True)

    seller_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
    )

    buyer_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=True,
    )

    efc_amount = Column(
        Numeric(18, 4),
        nullable=False,
    )

    price_uzs = Column(
        Numeric(18, 2),
        nullable=False,
    )

    seller_fee_efc = Column(
        Numeric(18, 4),
        default=0,
    )

    buyer_fee_uzs = Column(
        Numeric(18, 2),
        default=0,
    )

    total_buyer_pay_uzs = Column(
        Numeric(18, 2),
        default=0,
    )

    seller_receive_uzs = Column(
        Numeric(18, 2),
        default=0,
    )

    status = Column(
        String(20),
        default="OPEN",
    )

    reserved_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
