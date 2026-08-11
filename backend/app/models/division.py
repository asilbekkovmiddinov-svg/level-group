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


class DivisionMatchStatus(str, Enum):
    WAITING = "WAITING"
    MATCHED = "MATCHED"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class DivisionTicketState(str, Enum):
    LOCKED = "LOCKED"
    SPENT = "SPENT"
    REFUNDED = "REFUNDED"


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


class DivisionMatch(Base):
    __tablename__ = "division_matches"
    __table_args__ = (
        CheckConstraint(
            "player_b_id IS NULL OR player_a_id <> player_b_id",
            name="ck_division_match_distinct_players",
        ),
        Index(
            "ix_division_matchmaking",
            "season_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_division_player_a_active",
            "player_a_id",
            "status",
        ),
        Index(
            "ix_division_player_b_active",
            "player_b_id",
            "status",
        ),
    )

    id = Column(String(36), primary_key=True)
    season_id = Column(
        Integer,
        ForeignKey("division_seasons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    player_a_id = Column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    player_b_id = Column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=True, index=True
    )
    status = Column(
        SQLEnum(DivisionMatchStatus, native_enum=False),
        nullable=False,
        default=DivisionMatchStatus.WAITING,
        index=True,
    )
    player_a_ticket_state = Column(
        SQLEnum(DivisionTicketState, native_enum=False),
        nullable=False,
        default=DivisionTicketState.LOCKED,
    )
    player_b_ticket_state = Column(
        SQLEnum(DivisionTicketState, native_enum=False), nullable=True
    )
    arena_match_id = Column(
        Integer, ForeignKey("arena_matches.id", ondelete="SET NULL"), nullable=True
    )
    winner_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    loser_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    player_a_score = Column(Integer)
    player_b_score = Column(Integer)
    cancel_reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    matched_at = Column(DateTime(timezone=True))
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class DivisionTicketLedger(Base):
    __tablename__ = "division_ticket_ledger"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_division_ticket_ledger_idempotency"
        ),
        CheckConstraint(
            "available_delta <> 0 OR locked_delta <> 0",
            name="ck_division_ticket_ledger_nonzero",
        ),
        Index(
            "ix_division_ticket_ledger_user_created",
            "telegram_id",
            "created_at",
        ),
    )

    id = Column(String(36), primary_key=True)
    telegram_id = Column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    match_id = Column(
        String(36),
        ForeignKey("division_matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation = Column(String(24), nullable=False)
    available_delta = Column(Integer, nullable=False, default=0)
    locked_delta = Column(Integer, nullable=False, default=0)
    idempotency_key = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
