from sqlalchemy import Column, BigInteger, Numeric, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.core.database import Base


class Wallet(Base):
    __tablename__ = "wallets"

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        primary_key=True
    )

    efc_balance = Column(Numeric(18, 2), default=0)
    uzs_balance = Column(Numeric(18, 2), default=0)

    locked_efc = Column(Numeric(18, 2), default=0)
    locked_uzs = Column(Numeric(18, 2), default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
