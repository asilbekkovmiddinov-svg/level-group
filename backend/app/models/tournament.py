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
from sqlalchemy.orm import relationship

from app.core.database import Base


TOURNAMENT_TICKET_COST = 10
MAX_TOURNAMENT_PARTICIPANTS = 8192


def utc_now():
    return datetime.now(timezone.utc)


class TournamentFormat(str, Enum):
    SINGLE_ELIMINATION = "SINGLE_ELIMINATION"
    GROUP_PLAYOFF = "GROUP_PLAYOFF"


class TournamentGroupMode(str, Enum):
    POINTS = "POINTS"
    ELIMINATION = "ELIMINATION"


class TournamentStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION = "REGISTRATION"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class TournamentParticipantStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ELIMINATED = "ELIMINATED"
    WITHDRAWN = "WITHDRAWN"


class TournamentMatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    READY = "READY"
    PLAYING = "PLAYING"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class Tournament(Base):
    __tablename__ = "tournaments"
    __table_args__ = (
        CheckConstraint(
            f"max_participants BETWEEN 2 AND {MAX_TOURNAMENT_PARTICIPANTS}",
            name="ck_tournament_capacity",
        ),
        CheckConstraint(
            "ticket_cost BETWEEN 0 AND 1000000",
            name="ck_tournament_ticket_cost",
        ),
        CheckConstraint(
            "(format = 'SINGLE_ELIMINATION' AND group_count IS NULL "
            "AND qualifiers_per_group IS NULL AND group_size IS NULL "
            "AND group_mode IS NULL) OR "
            "(format = 'GROUP_PLAYOFF' AND group_count >= 1 "
            "AND qualifiers_per_group >= 1 AND group_size IN (4, 8) "
            "AND group_mode IN ('POINTS', 'ELIMINATION'))",
            name="ck_tournament_format_settings",
        ),
        Index("ix_tournament_status_dates", "status", "starts_at", "ends_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    format = Column(SQLEnum(TournamentFormat, native_enum=False), nullable=False)
    status = Column(
        SQLEnum(TournamentStatus, native_enum=False),
        nullable=False,
        default=TournamentStatus.DRAFT,
        index=True,
    )
    max_participants = Column(Integer, nullable=False)
    ticket_cost = Column(Integer, nullable=False, default=TOURNAMENT_TICKET_COST)
    group_count = Column(Integer)
    group_size = Column(Integer)
    group_mode = Column(SQLEnum(TournamentGroupMode, native_enum=False))
    qualifiers_per_group = Column(Integer)
    registration_opens_at = Column(DateTime(timezone=True), nullable=False)
    registration_closes_at = Column(DateTime(timezone=True), nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class TournamentParticipant(Base):
    __tablename__ = "tournament_participants"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "telegram_id", name="uq_tournament_participant_user"
        ),
        UniqueConstraint(
            "tournament_id", "seed", name="uq_tournament_participant_seed"
        ),
        CheckConstraint("seed IS NULL OR seed >= 1", name="ck_tournament_seed"),
        CheckConstraint("points >= 0", name="ck_tournament_points"),
        CheckConstraint("wins >= 0", name="ck_tournament_wins"),
        CheckConstraint("losses >= 0", name="ck_tournament_losses"),
        Index("ix_tournament_applications", "tournament_id", "status", "applied_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tournament_id = Column(
        Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    telegram_id = Column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    status = Column(
        SQLEnum(TournamentParticipantStatus, native_enum=False),
        nullable=False,
        default=TournamentParticipantStatus.PENDING,
        index=True,
    )
    seed = Column(Integer)
    group_name = Column(String(16))
    entry_ticket_state = Column(String(16))
    played = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    points = Column(Integer, nullable=False, default=0)
    goals_for = Column(Integer, nullable=False, default=0)
    goals_against = Column(Integer, nullable=False, default=0)
    advanced_round = Column(Integer, nullable=False, default=0)
    applied_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    reviewed_at = Column(DateTime(timezone=True))
    reviewed_by = Column(BigInteger)
    user = relationship("User", foreign_keys=[telegram_id])

    @property
    def username(self):
        return self.user.username if self.user else None

    @property
    def first_name(self):
        return self.user.first_name if self.user else None

    @property
    def last_name(self):
        return self.user.last_name if self.user else None


class TournamentMatch(Base):
    __tablename__ = "tournament_matches"
    __table_args__ = (
        CheckConstraint("player_a_id <> player_b_id", name="ck_tournament_distinct_players"),
        CheckConstraint("round_number >= 1", name="ck_tournament_round"),
        CheckConstraint(
            "player_a_score IS NULL OR player_a_score >= 0",
            name="ck_tournament_player_a_score",
        ),
        CheckConstraint(
            "player_b_score IS NULL OR player_b_score >= 0",
            name="ck_tournament_player_b_score",
        ),
        Index(
            "ix_tournament_match_schedule",
            "tournament_id",
            "scheduled_at",
            "status",
        ),
    )

    id = Column(String(36), primary_key=True)
    tournament_id = Column(
        Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    player_a_id = Column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    player_b_id = Column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    round_number = Column(Integer, nullable=False)
    round_name = Column(String(32), nullable=False)
    group_name = Column(String(16))
    scheduled_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(
        SQLEnum(TournamentMatchStatus, native_enum=False),
        nullable=False,
        default=TournamentMatchStatus.SCHEDULED,
        index=True,
    )
    arena_match_id = Column(
        Integer, ForeignKey("arena_matches.id", ondelete="SET NULL"), nullable=True
    )
    player_a_ticket_state = Column(String(16))
    player_b_ticket_state = Column(String(16))
    winner_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    player_a_score = Column(Integer)
    player_b_score = Column(Integer)
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
