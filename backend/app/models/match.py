from enum import Enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class MatchStatus(str, Enum):
    WAITING_PLAYER = "WAITING_PLAYER"
    SCHEDULED = "SCHEDULED"
    READY_CHECK = "READY_CHECK"
    WAITING_ROOM_CODE = "WAITING_ROOM_CODE"
    ROOM_CREATED = "ROOM_CREATED"
    MATCH_STARTED = "MATCH_STARTED"
    WAITING_ADMIN = "WAITING_ADMIN"
    TECHNICAL_WIN = "TECHNICAL_WIN"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class MatchResultType(str, Enum):
    NORMAL = "NORMAL"
    TECHNICAL = "TECHNICAL"
    CANCELLED = "CANCELLED"


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)

    creator_telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True,
    )

    opponent_telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=True,
        index=True,
    )

    creator = relationship(
        "User",
        foreign_keys=[creator_telegram_id],
    )

    opponent = relationship(
        "User",
        foreign_keys=[opponent_telegram_id],
    )

    @property
    def creator_username(self):
        return self.creator.username if self.creator else None

    @property
    def creator_first_name(self):
        return self.creator.first_name if self.creator else None

    @property
    def opponent_username(self):
        return self.opponent.username if self.opponent else None

    @property
    def opponent_first_name(self):
        return self.opponent.first_name if self.opponent else None

    efc_amount = Column(Numeric(18, 2), nullable=False)
    total_pool = Column(Numeric(18, 2), nullable=False)
    commission_amount = Column(Numeric(18, 2), nullable=False)
    winner_reward = Column(Numeric(18, 2), nullable=False)

    status = Column(
        SQLEnum(MatchStatus),
        nullable=False,
        default=MatchStatus.WAITING_PLAYER,
        index=True,
    )

    scheduled_at = Column(DateTime, nullable=False, index=True)

    ready_check_started_at = Column(DateTime, nullable=True)
    ready_check_deadline_at = Column(DateTime, nullable=True)

    creator_ready = Column(Boolean, nullable=False, default=False)
    opponent_ready = Column(Boolean, nullable=False, default=False)

    creator_ready_at = Column(DateTime, nullable=True)
    opponent_ready_at = Column(DateTime, nullable=True)

    room_code = Column(String(64), nullable=True)
    room_code_created_by = Column(BigInteger, nullable=True)
    room_code_created_at = Column(DateTime, nullable=True)

    creator_result_screenshot = Column(String(500), nullable=True)
    opponent_result_screenshot = Column(String(500), nullable=True)

    creator_result_uploaded_at = Column(DateTime, nullable=True)
    opponent_result_uploaded_at = Column(DateTime, nullable=True)

    winner_telegram_id = Column(BigInteger, nullable=True, index=True)
    loser_telegram_id = Column(BigInteger, nullable=True, index=True)

    result_type = Column(
        SQLEnum(MatchResultType),
        nullable=True,
    )

    admin_telegram_id = Column(BigInteger, nullable=True)
    admin_comment = Column(String(255), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    cancel_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class MatchStats(Base):
    __tablename__ = "match_stats"

    id = Column(Integer, primary_key=True, index=True)

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        unique=True,
        index=True,
    )

    total_matches = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)

    win_rate = Column(Numeric(5, 2), nullable=False, default=0)

    win_streak = Column(Integer, nullable=False, default=0)
    best_win_streak = Column(Integer, nullable=False, default=0)

    total_efc_won = Column(Numeric(18, 2), nullable=False, default=0)
    total_efc_lost = Column(Numeric(18, 2), nullable=False, default=0)
    biggest_win = Column(Numeric(18, 2), nullable=False, default=0)

    rating = Column(Integer, nullable=False, default=1000)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
