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
    WAITING_ADMIN = "WAITING_ADMIN"
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
    OPEN = "OPEN"
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ArenaV3EvidenceStatus(str, Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"


class ArenaV4RewardHoldStatus(str, Enum):
    NONE = "NONE"
    LOCKED = "LOCKED"
    APPEAL_HOLD = "APPEAL_HOLD"
    AVAILABLE = "AVAILABLE"
    REVERSED = "REVERSED"


class ArenaV4AdminReviewStatus(str, Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DECIDED = "DECIDED"


class ArenaV4ReviewType(str, Enum):
    INITIAL = "INITIAL"
    APPEAL = "APPEAL"


class ArenaV4ResultType(str, Enum):
    PLAYER_A_WIN = "PLAYER_A_WIN"
    PLAYER_B_WIN = "PLAYER_B_WIN"
    DRAW = "DRAW"
    CANCEL = "CANCEL"


class ArenaV4SettlementOperationStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REVERSED = "REVERSED"
    FAILED = "FAILED"


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
    has_appeal = Column(Boolean, nullable=False, default=False, index=True)
    reward_hold_status = Column(
        SQLEnum(ArenaV4RewardHoldStatus, native_enum=False),
        nullable=False, default=ArenaV4RewardHoldStatus.NONE, index=True,
    )
    reward_release_at = Column(DateTime(timezone=True), index=True)
    current_result_type = Column(
        SQLEnum(ArenaV4ResultType, native_enum=False), index=True
    )
    result_version = Column(Integer, nullable=False, default=0)
    current_decision_id = Column(
        Integer, ForeignKey("arena_admin_reviews.id", use_alter=True)
    )
    initial_decision_id = Column(
        Integer, ForeignKey("arena_admin_reviews.id", use_alter=True)
    )
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
    admin_reviews = relationship(
        "ArenaV4AdminReview",
        back_populates="match",
        cascade="all, delete-orphan",
        foreign_keys="ArenaV4AdminReview.match_id",
    )
    result_revisions = relationship(
        "ArenaV4ResultRevision", back_populates="match", cascade="all, delete-orphan"
    )
    settlement_operations = relationship(
        "ArenaV4SettlementOperation",
        back_populates="match",
        cascade="all, delete-orphan",
        foreign_keys="ArenaV4SettlementOperation.match_id",
    )
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
        UniqueConstraint("match_id", name="uq_arena_appeal_match"),
        UniqueConstraint("match_id", "submitted_by", name="uq_arena_appeal_submitter"),
        Index("ix_arena_appeal_status_created", "status", "created_at"),
        Index("ix_arena_appeal_deadline", "deadline_at"),
    )

    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("arena_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    submitted_by = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True, index=True)
    reason_code = Column(String(64), nullable=False)
    reason = Column(String(500))
    comment = Column(String(500))
    video_storage_key = Column(String(500))
    telegram_file_id = Column(String(500))
    file_hash = Column(String(64))
    status = Column(SQLEnum(ArenaV3AppealStatus, native_enum=False), nullable=False, default=ArenaV3AppealStatus.OPEN)
    admin_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    resolution = Column(String(32))
    admin_comment = Column(String(500))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    submitted_at = Column(DateTime(timezone=True))
    deadline_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))

    match = relationship("ArenaV3Match", back_populates="appeals")


class ArenaV4AdminReview(Base):
    __tablename__ = "arena_admin_reviews"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "review_type", "result_version",
            name="uq_arena_admin_review_version",
        ),
        UniqueConstraint("idempotency_key", name="uq_arena_admin_review_idempotency"),
        CheckConstraint(
            "owner_score IS NULL OR owner_score >= 0",
            name="ck_arena_admin_review_owner_score",
        ),
        CheckConstraint(
            "opponent_score IS NULL OR opponent_score >= 0",
            name="ck_arena_admin_review_opponent_score",
        ),
        Index("ix_arena_admin_review_queue", "status", "created_at"),
        Index("ix_arena_admin_review_match_type", "match_id", "review_type"),
    )

    id = Column(Integer, primary_key=True)
    match_id = Column(
        Integer, ForeignKey("arena_matches.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    review_type = Column(
        SQLEnum(ArenaV4ReviewType, native_enum=False), nullable=False
    )
    status = Column(
        SQLEnum(ArenaV4AdminReviewStatus, native_enum=False),
        nullable=False, default=ArenaV4AdminReviewStatus.PENDING,
    )
    result_version = Column(Integer, nullable=False, default=0)
    assigned_admin_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    decision = Column(SQLEnum(ArenaV4ResultType, native_enum=False))
    owner_score = Column(Integer)
    opponent_score = Column(Integer)
    reason = Column(String(500))
    expected_match_version = Column(Integer)
    idempotency_key = Column(String(128))
    claimed_at = Column(DateTime(timezone=True))
    decided_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=utc_now, onupdate=utc_now,
    )

    match = relationship(
        "ArenaV3Match", back_populates="admin_reviews", foreign_keys=[match_id]
    )


class ArenaV4ResultRevision(Base):
    __tablename__ = "arena_result_revisions"
    __table_args__ = (
        UniqueConstraint("match_id", "version", name="uq_arena_result_revision"),
        Index("ix_arena_result_revision_match_created", "match_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    match_id = Column(
        Integer, ForeignKey("arena_matches.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version = Column(Integer, nullable=False)
    review_id = Column(Integer, ForeignKey("arena_admin_reviews.id"))
    appeal_id = Column(Integer, ForeignKey("arena_appeals.id"))
    previous_result_type = Column(String(32))
    new_result_type = Column(String(32), nullable=False)
    previous_winner_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    new_winner_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    previous_owner_score = Column(Integer)
    previous_opponent_score = Column(Integer)
    new_owner_score = Column(Integer)
    new_opponent_score = Column(Integer)
    previous_reward_efc = Column(Numeric(18, 2))
    new_reward_efc = Column(Numeric(18, 2))
    previous_fee_efc = Column(Numeric(18, 2))
    new_fee_efc = Column(Numeric(18, 2))
    admin_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    reason = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    match = relationship("ArenaV3Match", back_populates="result_revisions")


class ArenaV4SettlementOperation(Base):
    __tablename__ = "arena_settlement_operations"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_arena_settlement_operation_idempotency"
        ),
        CheckConstraint("amount_efc >= 0", name="ck_arena_settlement_amount"),
        Index("ix_arena_settlement_match_version", "match_id", "result_version"),
        Index("ix_arena_settlement_status_created", "status", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    match_id = Column(
        Integer, ForeignKey("arena_matches.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    result_version = Column(Integer, nullable=False)
    player_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    operation_type = Column(String(32), nullable=False)
    amount_efc = Column(Numeric(18, 2), nullable=False)
    status = Column(
        SQLEnum(ArenaV4SettlementOperationStatus, native_enum=False),
        nullable=False, default=ArenaV4SettlementOperationStatus.PENDING,
    )
    wallet_transaction_id = Column(Integer, ForeignKey("transactions.id"))
    reverses_operation_id = Column(
        Integer, ForeignKey("arena_settlement_operations.id")
    )
    idempotency_key = Column(String(128), nullable=False)
    operation_metadata = Column("metadata", JSON)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at = Column(DateTime(timezone=True))

    match = relationship(
        "ArenaV3Match",
        back_populates="settlement_operations",
        foreign_keys=[match_id],
    )


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
    draws = Column(Integer, nullable=False, default=0)
    goals_for = Column(Integer, nullable=False, default=0)
    goals_against = Column(Integer, nullable=False, default=0)
    win_rate = Column(Numeric(5, 2), nullable=False, default=0)
    total_efc_won = Column(Numeric(18, 2), nullable=False, default=0)
    total_efc_lost = Column(Numeric(18, 2), nullable=False, default=0)
    current_streak = Column(Integer, nullable=False, default=0)
    best_streak = Column(Integer, nullable=False, default=0)
    rating = Column(Integer, nullable=False, default=1000)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
