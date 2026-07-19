from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


CAMPAIGN_AUDIENCES = (
    "ALL_USERS", "REFERRAL_USERS", "COIN_SHOP_USERS", "ARENA_USERS",
    "WHEEL_USERS", "INACTIVE_USERS", "VIP_USERS", "CUSTOM",
)
CAMPAIGN_SCHEDULE_TYPES = ("NOW", "SCHEDULED")
CAMPAIGN_STATUSES = (
    "DRAFT", "SCHEDULED", "RUNNING", "COMPLETED", "FAILED", "PAUSED",
    "CANCELLED", "DELETED",
)
CAMPAIGN_ACTIONS = (
    "NONE", "COIN_SHOP", "REFERRAL", "ARENA", "WHEEL", "PROFILE", "URL", "CUSTOM",
)


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint("audience_type IN ('ALL_USERS','REFERRAL_USERS','COIN_SHOP_USERS','ARENA_USERS','WHEEL_USERS','INACTIVE_USERS','VIP_USERS','CUSTOM')", name="ck_campaigns_audience_type"),
        CheckConstraint("schedule_type IN ('NOW','SCHEDULED')", name="ck_campaigns_schedule_type"),
        CheckConstraint("status IN ('DRAFT','SCHEDULED','RUNNING','COMPLETED','FAILED','PAUSED','CANCELLED','DELETED')", name="ck_campaigns_status"),
        CheckConstraint("button_action IN ('NONE','COIN_SHOP','REFERRAL','ARENA','WHEEL','PROFILE','URL','CUSTOM')", name="ck_campaigns_button_action"),
        CheckConstraint("schedule_type != 'SCHEDULED' OR scheduled_at IS NOT NULL", name="ck_campaigns_scheduled_at_required"),
        CheckConstraint("sent_count >= 0 AND opened_count >= 0 AND clicked_count >= 0 AND failed_count >= 0", name="ck_campaigns_counts_non_negative"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(160), nullable=False)
    message = Column(Text, nullable=False)
    image_url = Column(String(1000), nullable=True)
    button_text = Column(String(100), nullable=True)
    button_action = Column(String(30), nullable=False, default="NONE")
    button_target = Column(String(1000), nullable=True)
    promotion_id = Column(Integer, ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True, index=True)
    audience_type = Column(String(30), nullable=False, default="ALL_USERS", index=True)
    schedule_type = Column(String(20), nullable=False, default="NOW")
    scheduled_at = Column(DateTime(timezone=True), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="DRAFT", index=True)
    sent_count = Column(Integer, nullable=False, default=0)
    opened_count = Column(Integer, nullable=False, default=0)
    clicked_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    created_by = Column(BigInteger, nullable=False)
    updated_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)
