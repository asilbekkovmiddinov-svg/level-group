from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from app.core.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class ArenaV5SeasonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"


class ArenaV5Season(Base):
    __tablename__ = "arena_v5_seasons"
    __table_args__ = (
        CheckConstraint(
            "duration_days BETWEEN 1 AND 365",
            name="ck_arena_v5_season_duration_range",
        ),
        CheckConstraint("points_for_win = 3", name="ck_arena_v5_win_points"),
        CheckConstraint("points_for_draw = 1", name="ck_arena_v5_draw_points"),
        CheckConstraint("points_for_loss = 0", name="ck_arena_v5_loss_points"),
        CheckConstraint("referral_points = 3", name="ck_arena_v5_referral_points"),
        Index("ix_arena_v5_season_status_dates", "status", "starts_at", "ends_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    status = Column(
        SQLEnum(ArenaV5SeasonStatus, native_enum=False),
        nullable=False,
        default=ArenaV5SeasonStatus.ACTIVE,
        index=True,
    )
    duration_days = Column(Integer, nullable=False)
    points_for_win = Column(Integer, nullable=False, default=3)
    points_for_draw = Column(Integer, nullable=False, default=1)
    points_for_loss = Column(Integer, nullable=False, default=0)
    referral_points = Column(Integer, nullable=False, default=3)
    prize_text = Column(String(500), nullable=True)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(BigInteger, nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ArenaV5ReferralPoint(Base):
    __tablename__ = "arena_v5_referral_points"
    __table_args__ = (
        UniqueConstraint(
            "season_id", "referral_id", name="uq_arena_v5_season_referral"
        ),
        CheckConstraint("points = 3", name="ck_arena_v5_referral_award_points"),
        Index("ix_arena_v5_referral_ranking", "season_id", "referrer_telegram_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    season_id = Column(
        Integer,
        ForeignKey("arena_v5_seasons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    referral_id = Column(
        Integer, ForeignKey("referrals.id", ondelete="CASCADE"), nullable=False
    )
    referrer_telegram_id = Column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    referred_telegram_id = Column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False
    )
    points = Column(Integer, nullable=False, default=3)
    awarded_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
