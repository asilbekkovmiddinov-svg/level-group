"""internal campaign delivery contract

Revision ID: 20260719_internal_delivery
Revises: 20260719_user_notifications
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_internal_delivery"
down_revision = "20260719_user_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("campaign_recipients", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaign_recipients", sa.Column("last_failed_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaign_recipients", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaign_recipients", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaign_recipients", sa.Column("failure_reason", sa.String(length=500), nullable=True))
    op.add_column("campaign_recipients", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaign_recipients", sa.Column("delivery_time", sa.Float(), nullable=True))
    op.create_index("ix_campaign_recipients_claimed_at", "campaign_recipients", ["claimed_at"])


def downgrade():
    op.drop_index("ix_campaign_recipients_claimed_at", table_name="campaign_recipients")
    op.drop_column("campaign_recipients", "delivery_time")
    op.drop_column("campaign_recipients", "retry_count")
    op.drop_column("campaign_recipients", "failure_reason")
    op.drop_column("campaign_recipients", "failed_at")
    op.drop_column("campaign_recipients", "sent_at")
    op.drop_column("campaign_recipients", "last_failed_claimed_at")
    op.drop_column("campaign_recipients", "claimed_at")
