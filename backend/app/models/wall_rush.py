from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, Enum as SQLEnum, ForeignKey,
    Index, Integer, JSON, String, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class WallRushMode(str, Enum):
    FREE = "FREE"
    TICKET = "TICKET"


class WallRushStatus(str, Enum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class WallRushActionType(str, Enum):
    MOVE = "MOVE"
    WALL = "WALL"


class TicketKind(str, Enum):
    GAME = "GAME"
    TOURNAMENT = "TOURNAMENT"


class WallRushMatch(Base):
    __tablename__ = "wall_rush_matches"
    __table_args__ = (
        CheckConstraint("red_player_id <> blue_player_id", name="ck_wall_rush_distinct_players"),
        CheckConstraint("red_walls_remaining BETWEEN 0 AND 10", name="ck_wall_rush_red_walls"),
        CheckConstraint("blue_walls_remaining BETWEEN 0 AND 10", name="ck_wall_rush_blue_walls"),
        CheckConstraint("turn_number > 0", name="ck_wall_rush_turn_number"),
        CheckConstraint("red_missed_turns BETWEEN 0 AND 3", name="ck_wall_rush_red_misses"),
        CheckConstraint("blue_missed_turns BETWEEN 0 AND 3", name="ck_wall_rush_blue_misses"),
        Index("ix_wall_rush_matchmaking", "mode", "status", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    mode = Column(SQLEnum(WallRushMode, native_enum=False), nullable=False, index=True)
    status = Column(SQLEnum(WallRushStatus, native_enum=False), nullable=False, default=WallRushStatus.WAITING, index=True)
    red_player_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    blue_player_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True, index=True)
    current_turn_player_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    red_row = Column(Integer, nullable=False, default=12)
    red_column = Column(Integer, nullable=False, default=2)
    blue_row = Column(Integer, nullable=False, default=12)
    blue_column = Column(Integer, nullable=False, default=6)
    red_walls_remaining = Column(Integer, nullable=False, default=10)
    blue_walls_remaining = Column(Integer, nullable=False, default=10)
    red_missed_turns = Column(Integer, nullable=False, default=0)
    blue_missed_turns = Column(Integer, nullable=False, default=0)
    walls = Column(JSON, nullable=False, default=list)
    turn_number = Column(Integer, nullable=False, default=1)
    turn_deadline_at = Column(DateTime(timezone=True))
    winner_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True, index=True)
    cancel_reason = Column(String(255))
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    red_player = relationship("User", foreign_keys=[red_player_id])
    blue_player = relationship("User", foreign_keys=[blue_player_id])
    actions = relationship("WallRushAction", back_populates="match", cascade="all, delete-orphan")


class WallRushAction(Base):
    __tablename__ = "wall_rush_actions"
    __table_args__ = (
        UniqueConstraint("match_id", "sequence", name="uq_wall_rush_action_sequence"),
        UniqueConstraint("match_id", "idempotency_key", name="uq_wall_rush_action_idempotency"),
    )

    id = Column(String(36), primary_key=True)
    match_id = Column(String(36), ForeignKey("wall_rush_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    action_type = Column(SQLEnum(WallRushActionType, native_enum=False), nullable=False)
    payload = Column(JSON, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    match = relationship("WallRushMatch", back_populates="actions")


class GameTicketWallet(Base):
    __tablename__ = "game_ticket_wallets"
    __table_args__ = (
        CheckConstraint("game_tickets >= 0", name="ck_game_ticket_wallet_game"),
        CheckConstraint("locked_game_tickets >= 0", name="ck_game_ticket_wallet_locked"),
        CheckConstraint("tournament_tickets >= 0", name="ck_game_ticket_wallet_tournament"),
        CheckConstraint(
            "locked_tournament_tickets >= 0",
            name="ck_game_ticket_wallet_locked_tournament",
        ),
    )

    telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"), primary_key=True)
    game_tickets = Column(Integer, nullable=False, default=0)
    locked_game_tickets = Column(Integer, nullable=False, default=0)
    tournament_tickets = Column(Integer, nullable=False, default=0)
    locked_tournament_tickets = Column(Integer, nullable=False, default=0)
    last_rewarded_ad_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class GameTicketLedger(Base):
    __tablename__ = "game_ticket_ledger"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_game_ticket_ledger_idempotency"),
        CheckConstraint("amount <> 0", name="ck_game_ticket_ledger_nonzero"),
        Index("ix_game_ticket_ledger_user_created", "telegram_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    ticket_kind = Column(SQLEnum(TicketKind, native_enum=False), nullable=False)
    operation = Column(String(32), nullable=False)
    amount = Column(Integer, nullable=False)
    match_id = Column(String(36), ForeignKey("wall_rush_matches.id", ondelete="SET NULL"), nullable=True)
    idempotency_key = Column(String(128), nullable=False)
    metadata_json = Column("metadata", JSON)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
