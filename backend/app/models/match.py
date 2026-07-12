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
    WAITING_READY = "WAITING_READY"
    ROOM_READY = "ROOM_READY"
    PLAYING = "PLAYING"
    TECHNICAL_REVIEW = "TECHNICAL_REVIEW"
    WAITING_ADMIN = "WAITING_ADMIN"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"

    # Legacy names remain as aliases while the Arena service is migrated in
    # later sprints. Their persisted values are the target state values.
    SCHEDULED = WAITING_READY
    READY_CHECK = WAITING_READY
    WAITING_ROOM_CODE = ROOM_READY
    MATCH_STARTED = PLAYING
    TECHNICAL_WIN = TECHNICAL_REVIEW

    # This value was not part of the agreed legacy mapping. Keep it readable
    # for an existing row rather than coercing an unknown production state.
    ROOM_CREATED = "ROOM_CREATED"


class MatchGameType(str, Enum):
    EFOOTBALL = "EFOOTBALL"
    PUBG_MOBILE = "PUBG_MOBILE"
    FC_MOBILE = "FC_MOBILE"


LEGACY_MATCH_STATUS_MAPPING = {
    "WAITING_PLAYER": MatchStatus.WAITING_PLAYER.value,
    "SCHEDULED": MatchStatus.WAITING_READY.value,
    "READY_CHECK": MatchStatus.WAITING_READY.value,
    "WAITING_ROOM_CODE": MatchStatus.ROOM_READY.value,
    "MATCH_STARTED": MatchStatus.PLAYING.value,
    "TECHNICAL_WIN": MatchStatus.TECHNICAL_REVIEW.value,
    "WAITING_ADMIN": MatchStatus.WAITING_ADMIN.value,
    "COMPLETED": MatchStatus.COMPLETED.value,
    "CANCELLED": MatchStatus.CANCELLED.value,
}


def map_legacy_match_status(value: str) -> str | None:
    """Return a target status for a known legacy value, else preserve it."""
    return LEGACY_MATCH_STATUS_MAPPING.get(value)


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
        SQLEnum(MatchStatus, native_enum=False),
        nullable=False,
        default=MatchStatus.WAITING_PLAYER,
        index=True,
    )

    game_type = Column(
        SQLEnum(MatchGameType, native_enum=False),
        nullable=False,
        default=MatchGameType.EFOOTBALL,
        server_default=MatchGameType.EFOOTBALL.value,
    )

    scheduled_at = Column(DateTime, nullable=False, index=True)

    ready_check_started_at = Column(DateTime, nullable=True)
    ready_check_deadline_at = Column(DateTime, nullable=True)

    # Target-ready timestamps. The existing ready-check fields remain during
    # the compatibility period and will be retired only after the flow moves.
    ready_window_started_at = Column(DateTime(timezone=True), nullable=True)
    ready_deadline_at = Column(DateTime(timezone=True), nullable=True)

    creator_ready = Column(Boolean, nullable=False, default=False)
    opponent_ready = Column(Boolean, nullable=False, default=False)

    creator_ready_at = Column(DateTime(timezone=True), nullable=True)
    opponent_ready_at = Column(DateTime(timezone=True), nullable=True)

    creator_rules_accepted_at = Column(DateTime(timezone=True), nullable=True)
    opponent_rules_accepted_at = Column(DateTime(timezone=True), nullable=True)

    room_code = Column(String(64), nullable=True)
    room_code_created_by = Column(BigInteger, nullable=True)
    room_code_created_at = Column(DateTime, nullable=True)

    creator_result_screenshot = Column(String(500), nullable=True)
    opponent_result_screenshot = Column(String(500), nullable=True)

    creator_result_uploaded_at = Column(DateTime, nullable=True)
    opponent_result_uploaded_at = Column(DateTime, nullable=True)

    creator_result_video = Column(String(500), nullable=True)
    opponent_result_video = Column(String(500), nullable=True)
    creator_result_video_uploaded_at = Column(DateTime(timezone=True), nullable=True)
    opponent_result_video_uploaded_at = Column(DateTime(timezone=True), nullable=True)

    @property
    def creator_evidence_complete(self) -> bool:
        return bool(self.creator_result_screenshot and self.creator_result_video)

    @property
    def opponent_evidence_complete(self) -> bool:
        return bool(self.opponent_result_screenshot and self.opponent_result_video)

    @property
    def creator_display_name(self) -> str:
        return self.creator.first_name if self.creator and self.creator.first_name else "O‘yinchi"

    @property
    def opponent_display_name(self) -> str:
        return self.opponent.first_name if self.opponent and self.opponent.first_name else "O‘yinchi"

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
