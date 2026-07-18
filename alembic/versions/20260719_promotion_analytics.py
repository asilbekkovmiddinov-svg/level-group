"""Add promotion analytics event ledger.

Revision ID: 20260719_promotion_analytics
Revises: 20260719_promotion_banners
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_promotion_analytics"
down_revision = "20260719_promotion_banners"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("promotions", sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("promotions", sa.Column("last_clicked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "promotion_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("promotion_id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(10), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("event_type IN ('VIEW','CLICK')", name="ck_promotion_events_type"),
        sa.ForeignKeyConstraint(["promotion_id"], ["promotions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promotion_events_promotion_id", "promotion_events", ["promotion_id"])
    op.create_index("ix_promotion_events_telegram_id", "promotion_events", ["telegram_id"])
    op.create_index("ix_promotion_events_event_type", "promotion_events", ["event_type"])
    op.create_index("ix_promotion_events_occurred_at", "promotion_events", ["occurred_at"])
    op.create_index(
        "ix_promotion_events_analytics",
        "promotion_events",
        ["promotion_id", "event_type", "occurred_at", "telegram_id"],
    )


def downgrade():
    op.drop_index("ix_promotion_events_analytics", table_name="promotion_events")
    op.drop_index("ix_promotion_events_occurred_at", table_name="promotion_events")
    op.drop_index("ix_promotion_events_event_type", table_name="promotion_events")
    op.drop_index("ix_promotion_events_telegram_id", table_name="promotion_events")
    op.drop_index("ix_promotion_events_promotion_id", table_name="promotion_events")
    op.drop_table("promotion_events")
    op.drop_column("promotions", "last_clicked_at")
    op.drop_column("promotions", "last_viewed_at")
