from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey
)
from sqlalchemy.sql import func

from app.core.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False
    )

    currency = Column(String(10), nullable=False)

    amount = Column(Numeric(18, 2), nullable=False)

    balance_before = Column(Numeric(18, 2), nullable=False)

    balance_after = Column(Numeric(18, 2), nullable=False)

    type = Column(String(50), nullable=False)

    status = Column(String(20), default="SUCCESS")

    description = Column(String(255), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
