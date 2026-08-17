from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
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


def utc_now():
    return datetime.now(timezone.utc)


class PenaltyDuelMode(str, Enum):
    FREE = "FREE"
    TICKET = "TICKET"


class PenaltyDuelStatus(str, Enum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class PenaltyDuelMatch(Base):
    __tablename__ = "penalty_duel_matches"
    __table_args__ = (
        CheckConstraint(
            "player_one_id <> player_two_id",
            name="ck_penalty_duel_distinct_players",
        ),
        CheckConstraint("round_number > 0", name="ck_penalty_duel_round_positive"),
        CheckConstraint("player_one_score >= 0", name="ck_penalty_duel_p1_score"),
        CheckConstraint("player_two_score >= 0", name="ck_penalty_duel_p2_score"),
        Index(
            "ix_penalty_duel_matchmaking",
            "mode",
            "status",
            "created_at",
        ),
    )

    id = Column(String(36), primary_key=True)
    mode = Column(SQLEnum(PenaltyDuelMode, native_enum=False), nullable=False, index=True)
    status = Column(
        SQLEnum(PenaltyDuelStatus, native_enum=False),
        nullable=False,
        default=PenaltyDuelStatus.WAITING,
        index=True,
    )
    player_one_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    player_two_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True, index=True)
    round_number = Column(Integer, nullable=False, default=1)
    player_one_score = Column(Integer, nullable=False, default=0)
    player_two_score = Column(Integer, nullable=False, default=0)
    winner_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True, index=True)
    reward_granted = Column(Boolean, nullable=False, default=False)
    round_deadline_at = Column(DateTime(timezone=True))
    cancel_reason = Column(String(64))
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    player_one = relationship("User", foreign_keys=[player_one_id])
    player_two = relationship("User", foreign_keys=[player_two_id])
    submissions = relationship(
        "PenaltyDuelSubmission",
        back_populates="match",
        cascade="all, delete-orphan",
    )
    rounds = relationship(
        "PenaltyDuelRound",
        back_populates="match",
        cascade="all, delete-orphan",
    )


class PenaltyDuelSubmission(Base):
    __tablename__ = "penalty_duel_submissions"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "round_number",
            "player_id",
            name="uq_penalty_duel_round_player",
        ),
        UniqueConstraint("idempotency_key", name="uq_penalty_duel_submission_key"),
        CheckConstraint("round_number > 0", name="ck_penalty_duel_submission_round"),
    )

    id = Column(String(36), primary_key=True)
    match_id = Column(
        String(36),
        ForeignKey("penalty_duel_matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_number = Column(Integer, nullable=False)
    player_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    kick_direction = Column(String(16), nullable=False)
    keeper_direction = Column(String(16), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    match = relationship("PenaltyDuelMatch", back_populates="submissions")


class PenaltyDuelRound(Base):
    __tablename__ = "penalty_duel_rounds"
    __table_args__ = (
        UniqueConstraint("match_id", "round_number", name="uq_penalty_duel_round"),
        CheckConstraint("round_number > 0", name="ck_penalty_duel_result_round"),
        Index("ix_penalty_duel_round_match", "match_id", "round_number"),
    )

    id = Column(String(36), primary_key=True)
    match_id = Column(
        String(36),
        ForeignKey("penalty_duel_matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_number = Column(Integer, nullable=False)
    player_one_kick = Column(String(16), nullable=False)
    player_one_keeper = Column(String(16), nullable=False)
    player_two_kick = Column(String(16), nullable=False)
    player_two_keeper = Column(String(16), nullable=False)
    player_one_goal = Column(Boolean, nullable=False)
    player_two_goal = Column(Boolean, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    match = relationship("PenaltyDuelMatch", back_populates="rounds")
