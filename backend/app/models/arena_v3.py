from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, Enum as SQLEnum,
    ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class ArenaV3Status(str, Enum):
    OPEN = "OPEN"
    READY = "READY"
    WAITING_ROOM_CODE = "WAITING_ROOM_CODE"
    PLAYING = "PLAYING"
    WAITING_SCREENSHOT = "WAITING_SCREENSHOT"
    AI_REVIEW = "AI_REVIEW"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class ArenaV3SettlementStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"


class ArenaV3AIReviewStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    APPEAL_REQUIRED = "APPEAL_REQUIRED"


class ArenaV3AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ArenaV3EvidenceStatus(str, Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"


class ArenaV3Match(Base):
    __tablename__ = "arena_matches"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_arena_matches_public_id"),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_arena_matches_owner_idempotency"),
        CheckConstraint("stake_efc > 0", name="ck_arena_matches_positive_stake"),
        CheckConstraint("match_time_minutes BETWEEN 6 AND 15", name="ck_arena_matches_time"),
        CheckConstraint("penalties_enabled = true", name="ck_arena_matches_penalties_required"),
        CheckConstraint("owner_id <> opponent_id", name="ck_arena_matches_distinct_players"),
        CheckConstraint("owner_score IS NULL OR owner_score >= 0", name="ck_arena_matches_owner_score"),
        CheckConstraint("opponent_score IS NULL OR opponent_score >= 0", name="ck_arena_matches_opponent_score"),
        Index("ix_arena_matches_status_created", "status", "created_at"),
        Index("ix_arena_matches_status_stake", "status", "stake_efc"),
        Index("ix_arena_matches_screenshot_deadline", "screenshot_deadline_at"),
        Index("ix_arena_matches_playing_deadline", "playing_deadline_at"),
        Index("ix_arena_matches_appeal_deadline", "appeal_deadline_at"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(String(32), nullable=False)
    owner_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    opponent_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True, index=True)
    owner_efootball_username = Column(String(64), nullable=False)
    opponent_efootball_username = Column(String(64), nullable=True)
    stake_efc = Column(Numeric(18, 2), nullable=False)
    total_pool_efc = Column(Numeric(18, 2), nullable=False)
    commission_efc = Column(Numeric(18, 2), nullable=False)
    winner_reward_efc = Column(Numeric(18, 2), nullable=False)
    match_type = Column(String(32), nullable=False, index=True)
    match_time_minutes = Column(Integer, nullable=False)
    extra_time_enabled = Column(Boolean, nullable=False, default=False)
    penalties_enabled = Column(Boolean, nullable=False, default=True)
    status = Column(SQLEnum(ArenaV3Status, native_enum=False), nullable=False, default=ArenaV3Status.OPEN, index=True)
    owner_ready_at = Column(DateTime(timezone=True))
    opponent_ready_at = Column(DateTime(timezone=True))
    room_code = Column(String(8))
    room_code_created_at = Column(DateTime(timezone=True))
    playing_started_at = Column(DateTime(timezone=True))
    playing_deadline_at = Column(DateTime(timezone=True))
    screenshot_started_at = Column(DateTime(timezone=True))
    screenshot_deadline_at = Column(DateTime(timezone=True))
    ai_review_started_at = Column(DateTime(timezone=True))
    provisional_winner_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    winner_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    loser_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    owner_score = Column(Integer)
    opponent_score = Column(Integer)
    result_source = Column(String(24))
    appeal_deadline_at = Column(DateTime(timezone=True))
    settlement_status = Column(
        SQLEnum(ArenaV3SettlementStatus, native_enum=False),
        nullable=False, default=ArenaV3SettlementStatus.NOT_STARTED, index=True,
    )
    settled_at = Column(DateTime(timezone=True))
    cancel_reason = Column(String(255))
    finished_at = Column(DateTime(timezone=True))
    idempotency_key = Column(String(128))
    request_fingerprint = Column(String(64))
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    screenshots = relationship("ArenaV3MatchScreenshot", back_populates="match", cascade="all, delete-orphan")
    ai_reviews = relationship("ArenaV3AIReview", back_populates="match", cascade="all, delete-orphan")
    appeals = relationship("ArenaV3Appeal", back_populates="match", cascade="all, delete-orphan")
    events = relationship("ArenaV3MatchEvent", back_populates="match", cascade="all, delete-orphan")


class ArenaV3MatchScreenshot(Base):
    __tablename__ = "arena_match_screenshots"
    __table_args__ = (
        UniqueConstraint("match_id", "player_id", name="uq_arena_screenshot_player"),
        UniqueConstraint("match_id", "file_hash", name="uq_arena_screenshot_hash"),
        CheckConstraint("file_size > 0", name="ck_arena_screenshot_size"),
        CheckConstraint("width > 0 AND height > 0", name="ck_arena_screenshot_dimensions"),
        Index("ix_arena_screenshot_validation_uploaded", "validation_status", "uploaded_at"),
    )

    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("arena_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    storage_key = Column(String(500), nullable=False)
    telegram_file_id = Column(String(500))
    file_hash = Column(String(64), nullable=False, index=True)
    mime_type = Column(String(64), nullable=False)
    file_size = Column(Integer, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    validation_status = Column(SQLEnum(ArenaV3EvidenceStatus, native_enum=False), nullable=False, default=ArenaV3EvidenceStatus.PENDING)
    validation_reason = Column(String(255))
    identity_status = Column(String(24))
    extracted_owner_score = Column(Integer)
    extracted_opponent_score = Column(Integer)
    extraction_confidence = Column(Numeric(5, 4))
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    match = relationship("ArenaV3Match", back_populates="screenshots")


class ArenaV3AIReview(Base):
    __tablename__ = "arena_ai_reviews"
    __table_args__ = (Index("ix_arena_ai_review_status_created", "status", "created_at"),)

    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("arena_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(SQLEnum(ArenaV3AIReviewStatus, native_enum=False), nullable=False, default=ArenaV3AIReviewStatus.PENDING, index=True)
    owner_screenshot_id = Column(Integer, ForeignKey("arena_match_screenshots.id"))
    opponent_screenshot_id = Column(Integer, ForeignKey("arena_match_screenshots.id"))
    detected_owner_score = Column(Integer)
    detected_opponent_score = Column(Integer)
    provisional_winner_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    winner_player_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    score = Column(String(16))
    confidence = Column(Numeric(5, 4))
    reason_code = Column(String(64))
    reason = Column(String(255))
    conflict_type = Column(String(64))
    model_name = Column(String(100))
    model_version = Column(String(100))
    attempt_count = Column(Integer, nullable=False, default=0)
    raw_result = Column(JSON)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    match = relationship("ArenaV3Match", back_populates="ai_reviews")


class ArenaV3Appeal(Base):
    __tablename__ = "arena_appeals"
    __table_args__ = (
        UniqueConstraint("match_id", "submitted_by", name="uq_arena_appeal_submitter"),
        Index("ix_arena_appeal_status_created", "status", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("arena_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    submitted_by = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    reason_code = Column(String(64), nullable=False)
    comment = Column(String(500))
    video_storage_key = Column(String(500), nullable=False)
    telegram_file_id = Column(String(500))
    file_hash = Column(String(64), nullable=False)
    status = Column(SQLEnum(ArenaV3AppealStatus, native_enum=False), nullable=False, default=ArenaV3AppealStatus.SUBMITTED)
    admin_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    resolution = Column(String(32))
    admin_comment = Column(String(500))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    resolved_at = Column(DateTime(timezone=True))

    match = relationship("ArenaV3Match", back_populates="appeals")


class ArenaV3MatchEvent(Base):
    __tablename__ = "arena_match_events"
    __table_args__ = (
        UniqueConstraint("match_id", "idempotency_key", name="uq_arena_event_idempotency"),
        Index("ix_arena_event_match_created", "match_id", "created_at"),
        Index("ix_arena_event_to_status_created", "to_status", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("arena_matches.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(64), nullable=False, index=True)
    from_status = Column(String(32))
    to_status = Column(String(32))
    actor_type = Column(String(24), nullable=False)
    actor_id = Column(BigInteger)
    idempotency_key = Column(String(128), nullable=False)
    event_metadata = Column("metadata", JSON)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    match = relationship("ArenaV3Match", back_populates="events")


class ArenaV3NotificationDelivery(Base):
    __tablename__ = "arena_notification_deliveries_v3"
    __table_args__ = (Index("ix_arena_v3_delivery_status_created", "status", "created_at"),)

    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("arena_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    dedup_key = Column(String(255), nullable=False, unique=True)
    status = Column(String(16), nullable=False, default="PENDING")
    attempts = Column(Integer, nullable=False, default=0)
    message_id = Column(String(100))
    last_error = Column(Text)
    last_attempt_at = Column(DateTime(timezone=True))
    sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class ArenaV3Stats(Base):
    __tablename__ = "arena_stats_v3"
    __table_args__ = (
        CheckConstraint("total_matches >= 0 AND wins >= 0 AND losses >= 0", name="ck_arena_v3_stats_counts"),
        Index("ix_arena_v3_stats_wins", "wins"),
        Index("ix_arena_v3_stats_rating", "rating"),
        Index("ix_arena_v3_stats_total_efc_won", "total_efc_won"),
    )

    player_id = Column(BigInteger, ForeignKey("users.telegram_id"), primary_key=True)
    total_matches = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    total_efc_won = Column(Numeric(18, 2), nullable=False, default=0)
    total_efc_lost = Column(Numeric(18, 2), nullable=False, default=0)
    current_streak = Column(Integer, nullable=False, default=0)
    best_streak = Column(Integer, nullable=False, default=0)
    rating = Column(Integer, nullable=False, default=1000)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
