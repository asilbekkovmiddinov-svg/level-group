"""campaign execution engine

Revision ID: 20260719_campaign_execution
Revises: 20260719_campaign_center_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_campaign_execution"
down_revision = "20260719_campaign_center_v1"
branch_labels = None
depends_on = None


CAMPAIGN_STATUS_CHECK = "status IN ('DRAFT','SCHEDULED','READY','RUNNING','COMPLETED','FAILED','PAUSED','CANCELLED','DELETED')"
OLD_CAMPAIGN_STATUS_CHECK = "status IN ('DRAFT','SCHEDULED','RUNNING','COMPLETED','FAILED','PAUSED','CANCELLED','DELETED')"


def upgrade():
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_constraint("ck_campaigns_status", type_="check")
        batch.create_check_constraint("ck_campaigns_status", CAMPAIGN_STATUS_CHECK)
    op.create_table(
        "campaign_recipients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('PENDING','SENT','OPENED','CLICKED','FAILED','SKIPPED')", name="ck_campaign_recipients_status"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_campaign_recipient_user"),
    )
    op.create_index("ix_campaign_recipients_campaign_id", "campaign_recipients", ["campaign_id"])
    op.create_index("ix_campaign_recipients_user_id", "campaign_recipients", ["user_id"])
    op.create_index("ix_campaign_recipients_status", "campaign_recipients", ["status"])


def downgrade():
    op.drop_index("ix_campaign_recipients_status", table_name="campaign_recipients")
    op.drop_index("ix_campaign_recipients_user_id", table_name="campaign_recipients")
    op.drop_index("ix_campaign_recipients_campaign_id", table_name="campaign_recipients")
    op.drop_table("campaign_recipients")
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_constraint("ck_campaigns_status", type_="check")
        batch.create_check_constraint("ck_campaigns_status", OLD_CAMPAIGN_STATUS_CHECK)
