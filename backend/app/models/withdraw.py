from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    Numeric,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class Withdraw(Base):
    __tablename__ = "withdraws"
    __table_args__ = (UniqueConstraint("telegram_id", "idempotency_key", name="uq_withdraw_user_idempotency"),)

    id = Column(Integer, primary_key=True, index=True)

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
    )

    amount = Column(
        Numeric(18, 2),
        nullable=False,
    )

    card_number = Column(
        String(32),
        nullable=True,
    )

    card_holder = Column(
        String(120),
        nullable=True,
    )

    bank_name = Column(
        String(120),
        nullable=True,
    )

    status = Column(
        String(20),
        default="PENDING",
    )

    claimed_by = Column(BigInteger, nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)

    approved_by = Column(BigInteger, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    rejected_by = Column(BigInteger, nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)

    reject_reason = Column(String(255), nullable=True)

    processing_seconds = Column(Integer, nullable=True)

    notification_status = Column(String(20), nullable=False, default="PENDING")
    notification_sent_at = Column(DateTime(timezone=True), nullable=True)
    notification_message_id = Column(String(100), nullable=True)
    notification_attempts = Column(Integer, nullable=False, default=0)
    notification_last_error = Column(String(255), nullable=True)
    notification_last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    idempotency_key = Column(String(128), nullable=True)
    request_fingerprint = Column(String(64), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
