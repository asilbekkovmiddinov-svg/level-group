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


class Deposit(Base):
    __tablename__ = "deposits"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True
    )

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True
    )

    amount = Column(
        Numeric(18, 2),
        nullable=False
    )

    status = Column(
        String(30),
        default="PENDING"
    )
    # PENDING
    # CLAIMED
    # APPROVED
    # REJECTED

    card_number = Column(
        String(50),
        nullable=True
    )

    receipt_object_key = Column(String(500), nullable=True)
    receipt_content_type = Column(String(100), nullable=True)
    receipt_size = Column(Integer, nullable=True)
    receipt_uploaded_at = Column(DateTime(timezone=True), nullable=True)

    claimed_by = Column(
        BigInteger,
        nullable=True
    )

    claimed_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    completed_by = Column(
        BigInteger,
        nullable=True
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    approved_by = Column(
        BigInteger,
        nullable=True
    )

    approved_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    rejected_by = Column(
        BigInteger,
        nullable=True
    )

    rejected_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    reject_reason = Column(
        String(255),
        nullable=True
    )

    processing_seconds = Column(
        Integer,
        nullable=True
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
