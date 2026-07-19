"""user notification contract

Revision ID: 20260719_user_notifications
Revises: 20260719_campaign_execution
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_user_notifications"
down_revision = "20260719_campaign_execution"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("campaigns", sa.Column("badge", sa.String(length=80), nullable=True))
    op.add_column("campaign_recipients", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaign_recipients", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_campaign_recipients_dismissed_at", "campaign_recipients", ["dismissed_at"])


def downgrade():
    op.drop_index("ix_campaign_recipients_dismissed_at", table_name="campaign_recipients")
    op.drop_column("campaign_recipients", "dismissed_at")
    op.drop_column("campaign_recipients", "read_at")
    op.drop_column("campaigns", "badge")
