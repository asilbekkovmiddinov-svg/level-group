from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.core.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class ArenaTicketPromocode(Base):
    __tablename__ = "arena_ticket_promocodes"
    __table_args__ = (
        CheckConstraint("ticket_amount > 0", name="ck_arena_promocode_ticket_amount"),
        CheckConstraint("usage_limit IS NULL OR usage_limit > 0", name="ck_arena_promocode_usage_limit"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code = Column(String(32), nullable=False, unique=True, index=True)
    ticket_amount = Column(Integer, nullable=False)
    usage_limit = Column(Integer, nullable=True)
    usage_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class ArenaTicketPromocodeClaim(Base):
    __tablename__ = "arena_ticket_promocode_claims"
    __table_args__ = (
        UniqueConstraint("promocode_id", "telegram_id", name="uq_arena_promocode_claim_user"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    promocode_id = Column(String(36), ForeignKey("arena_ticket_promocodes.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    ticket_amount = Column(Integer, nullable=False)
    claimed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
