"""campaign center v1

Revision ID: 20260719_campaign_center_v1
Revises: 20260719_promotion_analytics
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_campaign_center_v1"
down_revision = "20260719_promotion_analytics"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
        sa.Column("button_text", sa.String(length=100), nullable=True),
        sa.Column("button_action", sa.String(length=30), nullable=False, server_default="NONE"),
        sa.Column("button_target", sa.String(length=1000), nullable=True),
        sa.Column("promotion_id", sa.Integer(), nullable=True),
        sa.Column("audience_type", sa.String(length=30), nullable=False, server_default="ALL_USERS"),
        sa.Column("schedule_type", sa.String(length=20), nullable=False, server_default="NOW"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opened_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("audience_type IN ('ALL_USERS','REFERRAL_USERS','COIN_SHOP_USERS','ARENA_USERS','WHEEL_USERS','INACTIVE_USERS','VIP_USERS','CUSTOM')", name="ck_campaigns_audience_type"),
        sa.CheckConstraint("schedule_type IN ('NOW','SCHEDULED')", name="ck_campaigns_schedule_type"),
        sa.CheckConstraint("status IN ('DRAFT','SCHEDULED','RUNNING','COMPLETED','FAILED','PAUSED','CANCELLED','DELETED')", name="ck_campaigns_status"),
        sa.CheckConstraint("button_action IN ('NONE','COIN_SHOP','REFERRAL','ARENA','WHEEL','PROFILE','URL','CUSTOM')", name="ck_campaigns_button_action"),
        sa.CheckConstraint("schedule_type != 'SCHEDULED' OR scheduled_at IS NOT NULL", name="ck_campaigns_scheduled_at_required"),
        sa.CheckConstraint("sent_count >= 0 AND opened_count >= 0 AND clicked_count >= 0 AND failed_count >= 0", name="ck_campaigns_counts_non_negative"),
        sa.ForeignKeyConstraint(["promotion_id"], ["promotions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaigns_promotion_id", "campaigns", ["promotion_id"])
    op.create_index("ix_campaigns_audience_type", "campaigns", ["audience_type"])
    op.create_index("ix_campaigns_scheduled_at", "campaigns", ["scheduled_at"])
    op.create_index("ix_campaigns_status", "campaigns", ["status"])


def downgrade():
    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_index("ix_campaigns_scheduled_at", table_name="campaigns")
    op.drop_index("ix_campaigns_audience_type", table_name="campaigns")
    op.drop_index("ix_campaigns_promotion_id", table_name="campaigns")
    op.drop_table("campaigns")
