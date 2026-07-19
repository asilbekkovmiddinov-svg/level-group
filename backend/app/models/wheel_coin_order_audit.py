from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class WheelCoinOrderAudit(Base):
    __tablename__ = "wheel_coin_order_audits"

    id = Column(Integer, primary_key=True)
    order_id = Column(
        Integer,
        ForeignKey("wheel_coin_orders.id"),
        nullable=False,
        index=True,
    )
    admin_telegram_id = Column(BigInteger, nullable=False, index=True)
    old_status = Column(String(30), nullable=False)
    new_status = Column(String(30), nullable=False)
    reason = Column(String(255), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
