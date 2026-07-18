"""Add Marketing CMS promotions foundation.

Revision ID: 20260719_promotions_v1
Revises: 20260719_referral_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_promotions_v1"
down_revision = "20260719_referral_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "promotions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("subtitle", sa.String(240), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("banner_url", sa.String(1000), nullable=True),
        sa.Column("badge", sa.String(80), nullable=True),
        sa.Column("button_text", sa.String(100), nullable=True),
        sa.Column("button_action", sa.String(30), nullable=False, server_default="NONE"),
        sa.Column("button_target", sa.String(1000), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_views", sa.Integer(), nullable=True),
        sa.Column("max_clicks", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('DRAFT','SCHEDULED','ACTIVE','PAUSED','EXPIRED','DELETED')",
            name="ck_promotions_status",
        ),
        sa.CheckConstraint(
            "button_action IN ('NONE','COIN_SHOP','REFERRAL','ARENA','WHEEL','PROFILE','URL','CUSTOM')",
            name="ck_promotions_button_action",
        ),
        sa.CheckConstraint("priority >= 0", name="ck_promotions_priority_non_negative"),
        sa.CheckConstraint("max_views IS NULL OR max_views > 0", name="ck_promotions_max_views_positive"),
        sa.CheckConstraint("max_clicks IS NULL OR max_clicks > 0", name="ck_promotions_max_clicks_positive"),
        sa.CheckConstraint("view_count >= 0", name="ck_promotions_view_count_non_negative"),
        sa.CheckConstraint("click_count >= 0", name="ck_promotions_click_count_non_negative"),
        sa.CheckConstraint("end_at IS NULL OR start_at IS NULL OR end_at > start_at", name="ck_promotions_valid_schedule"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promotions_priority", "promotions", ["priority"])
    op.create_index("ix_promotions_status", "promotions", ["status"])
    op.create_index("ix_promotions_start_at", "promotions", ["start_at"])
    op.create_index("ix_promotions_end_at", "promotions", ["end_at"])
    op.create_index(
        "ix_promotions_public_order",
        "promotions",
        ["status", "priority"],
    )


def downgrade():
    op.drop_index("ix_promotions_public_order", table_name="promotions")
    op.drop_index("ix_promotions_end_at", table_name="promotions")
    op.drop_index("ix_promotions_start_at", table_name="promotions")
    op.drop_index("ix_promotions_status", table_name="promotions")
    op.drop_index("ix_promotions_priority", table_name="promotions")
    op.drop_table("promotions")
