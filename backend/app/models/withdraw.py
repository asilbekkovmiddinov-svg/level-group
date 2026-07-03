from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    Numeric,
    String,
    DateTime,
    ForeignKey
)
from sqlalchemy.sql import func

from app.core.database import Base


class Withdraw(Base):
    __tablename__ = "withdraws"

    id = Column(Integer, primary_key=True, index=True)

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False
    )

    amount = Column(Numeric(18, 2), nullable=False)

    status = Column(
        String(20),
        default="PENDING"
    )

    approved_by = Column(
        BigInteger,
        nullable=True
    )

    approved_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
