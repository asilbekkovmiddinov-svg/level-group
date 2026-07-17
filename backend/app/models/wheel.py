from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    Numeric,
    String,
    Date,
    DateTime,
    Boolean,
    ForeignKey,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class WheelSettings(Base):
    __tablename__ = "wheel_settings"

    id = Column(Integer, primary_key=True, index=True)

    global_spin_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    next_130_coin_spin = Column(
        Integer,
        nullable=False,
        default=50000,
    )

    next_jackpot_spin = Column(
        Integer,
        nullable=False,
        default=100000,
    )

    jackpot_coin_amount = Column(
        Integer,
        nullable=False,
        default=2000,
    )

    coin_130_amount = Column(
        Integer,
        nullable=False,
        default=130,
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
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


class WheelDailyLimit(Base):
    __tablename__ = "wheel_daily_limits"

    id = Column(Integer, primary_key=True, index=True)

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True,
    )

    spin_date = Column(
        Date,
        nullable=False,
        index=True,
    )

    free_spin_used = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    ad_spin_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    bonus_spin_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    last_ad_spin_at = Column(
        DateTime(timezone=True),
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
class WheelSpin(Base):
    __tablename__ = "wheel_spins"

    id = Column(Integer, primary_key=True, index=True)

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True,
    )

    spin_type = Column(
        String(20),
        nullable=False,
        index=True,
    )

    reward_code = Column(
        String(50),
        nullable=False,
        index=True,
    )

    reward_type = Column(
        String(20),
        nullable=False,
    )

    reward_amount = Column(
        Numeric(18, 4),
        nullable=False,
        default=0,
    )

    global_spin_number = Column(
        Integer,
        nullable=False,
        index=True,
    )

    status = Column(
        String(20),
        nullable=False,
        default="COMPLETED",
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class WheelCoinOrder(Base):
    __tablename__ = "wheel_coin_orders"

    id = Column(Integer, primary_key=True, index=True)

    spin_id = Column(
        Integer,
        ForeignKey("wheel_spins.id"),
        nullable=False,
        index=True,
    )

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True,
    )

    username = Column(
        String(100),
        nullable=True,
    )

    first_name = Column(
        String(100),
        nullable=True,
    )

    coin_amount = Column(
        Integer,
        nullable=False,
    )

    konami_login = Column(
        String(255),
        nullable=True,
    )

    konami_password = Column(
        String(255),
        nullable=True,
    )

    region = Column(
        String(50),
        nullable=True,
    )

    device = Column(
        String(20),
        nullable=True,
    )

    status = Column(
        String(30),
        nullable=False,
        default="WAITING_DETAILS",
        index=True,
    )

    coin_notification_status = Column(String(20), nullable=False, default="PENDING")
    coin_notification_message_id = Column(String(100), nullable=True)
    coin_notification_attempts = Column(Integer, nullable=False, default=0)
    coin_notification_last_error = Column(String(255), nullable=True)
    coin_notification_sent_at = Column(DateTime(timezone=True), nullable=True)

    admin_id = Column(
        BigInteger,
        nullable=True,
    )

    reject_reason = Column(
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

    spin = relationship("WheelSpin")
