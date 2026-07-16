from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class CoinOrderMessage(Base):
    __tablename__ = "coin_order_messages"
    __table_args__ = (
        Index("ix_coin_order_messages_order", "order_type", "order_id", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_type = Column(String(10), nullable=False)
    order_id = Column(Integer, nullable=False)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    sender = Column(String(10), nullable=False)
    sender_id = Column(BigInteger, nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
