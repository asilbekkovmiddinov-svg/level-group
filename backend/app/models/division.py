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


class DivisionSeasonStatus(str, Enum):
    REGISTRATION = "REGISTRATION"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class DivisionParticipantStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DivisionSeason(Base):
    __tablename__ = "division_seasons"
    __table_args__ = (
        CheckConstraint("duration_days = 30", name="ck_division_season_duration"),
        CheckConstraint("ticket_cost = 1", name="ck_division_season_ticket_cost"),
        CheckConstraint("points_for_win = 3", name="ck_division_season_win_points"),
        CheckConstraint("points_for_loss = 0", name="ck_division_season_loss_points"),
        Index("ix_division_season_status_dates", "status", "starts_at", "ends_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    status = Column(
        SQLEnum(DivisionSeasonStatus, native_enum=False),
        nullable=False,
        default=DivisionSeasonStatus.REGISTRATION,
        index=True,
    )
    duration_days = Column(Integer, nullable=False, default=30)
    ticket_cost = Column(Integer, nullable=False, default=1)
    points_for_win = Column(Integer, nullable=False, default=3)
    points_for_loss = Column(Integer, nullable=False, default=0)
    registration_opens_at = Column(DateTime(timezone=True), nullable=False)
    registration_closes_at = Column(DateTime(timezone=True), nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class DivisionParticipant(Base):
    __tablename__ = "division_participants"
    __table_args__ = (
        UniqueConstraint(
            "season_id", "telegram_id", name="uq_division_participant_season_user"
        ),
        CheckConstraint("matches_played >= 0", name="ck_division_matches_played"),
        CheckConstraint("wins >= 0", name="ck_division_wins"),
        CheckConstraint("losses >= 0", name="ck_division_losses"),
        CheckConstraint("points >= 0", name="ck_division_points"),
        CheckConstraint("goals_for >= 0", name="ck_division_goals_for"),
        CheckConstraint("goals_against >= 0", name="ck_division_goals_against"),
        CheckConstraint(
            "matches_played = wins + losses", name="ck_division_match_totals"
        ),
        Index("ix_division_standings", "season_id", "status", "points", "wins"),
        Index("ix_division_applications", "season_id", "status", "applied_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    season_id = Column(
        Integer,
        ForeignKey("division_seasons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_id = Column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    status = Column(
        SQLEnum(DivisionParticipantStatus, native_enum=False),
        nullable=False,
        default=DivisionParticipantStatus.PENDING,
        index=True,
    )
    matches_played = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    points = Column(Integer, nullable=False, default=0)
    goals_for = Column(Integer, nullable=False, default=0)
    goals_against = Column(Integer, nullable=False, default=0)
    applied_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    reviewed_at = Column(DateTime(timezone=True))
    reviewed_by = Column(BigInteger)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
