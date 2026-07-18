from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


PROMOTION_STATUSES = (
    "DRAFT",
    "SCHEDULED",
    "ACTIVE",
    "PAUSED",
    "EXPIRED",
    "DELETED",
)
PROMOTION_ACTIONS = (
    "NONE",
    "COIN_SHOP",
    "REFERRAL",
    "ARENA",
    "WHEEL",
    "PROFILE",
    "URL",
    "CUSTOM",
)


class Promotion(Base):
    __tablename__ = "promotions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','SCHEDULED','ACTIVE','PAUSED','EXPIRED','DELETED')",
            name="ck_promotions_status",
        ),
        CheckConstraint(
            "button_action IN ('NONE','COIN_SHOP','REFERRAL','ARENA','WHEEL','PROFILE','URL','CUSTOM')",
            name="ck_promotions_button_action",
        ),
        CheckConstraint("priority >= 0", name="ck_promotions_priority_non_negative"),
        CheckConstraint("max_views IS NULL OR max_views > 0", name="ck_promotions_max_views_positive"),
        CheckConstraint("max_clicks IS NULL OR max_clicks > 0", name="ck_promotions_max_clicks_positive"),
        CheckConstraint("view_count >= 0", name="ck_promotions_view_count_non_negative"),
        CheckConstraint("click_count >= 0", name="ck_promotions_click_count_non_negative"),
        CheckConstraint("end_at IS NULL OR start_at IS NULL OR end_at > start_at", name="ck_promotions_valid_schedule"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(160), nullable=False)
    subtitle = Column(String(240), nullable=True)
    description = Column(Text, nullable=True)
    banner_url = Column(String(1000), nullable=True)
    banner_object_key = Column(String(500), nullable=True, unique=True)
    banner_content_type = Column(String(50), nullable=True)
    banner_size = Column(Integer, nullable=True)
    banner_updated_at = Column(DateTime(timezone=True), nullable=True)
    badge = Column(String(80), nullable=True)
    button_text = Column(String(100), nullable=True)
    button_action = Column(String(30), nullable=False, default="NONE")
    button_target = Column(String(1000), nullable=True)
    priority = Column(Integer, nullable=False, default=0, index=True)
    status = Column(String(20), nullable=False, default="DRAFT", index=True)
    start_at = Column(DateTime(timezone=True), nullable=True, index=True)
    end_at = Column(DateTime(timezone=True), nullable=True, index=True)
    max_views = Column(Integer, nullable=True)
    max_clicks = Column(Integer, nullable=True)
    view_count = Column(Integer, nullable=False, default=0)
    click_count = Column(Integer, nullable=False, default=0)
    created_by = Column(BigInteger, nullable=True)
    updated_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)
