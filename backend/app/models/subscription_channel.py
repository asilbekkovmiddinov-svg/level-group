from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class SubscriptionChannel(Base):
    __tablename__ = "subscription_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(128), nullable=False, unique=True, index=True)
    title = Column(String(120), nullable=False)
    url = Column(String(512), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0, index=True)
    created_by = Column(BigInteger, nullable=True)
    updated_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
