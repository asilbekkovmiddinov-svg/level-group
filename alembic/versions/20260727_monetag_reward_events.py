"""Monetag server-to-server rewarded events."""

from alembic import op
import sqlalchemy as sa


revision = "20260727_monetag_rewards"
down_revision = "20260726_adsgram_rewards"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "monetag_reward_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ymid", sa.String(64), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("status", sa.String(20), server_default="PENDING", nullable=False),
        sa.Column("zone_id", sa.String(50)),
        sa.Column("sub_zone_id", sa.String(100)),
        sa.Column("event", sa.String(30)),
        sa.Column("reward_type", sa.String(30)),
        sa.Column("estimated_price", sa.Numeric(18, 8)),
        sa.Column("source", sa.String(100), server_default="wheel_reward", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_monetag_reward_events_ymid", "monetag_reward_events", ["ymid"], unique=True)
    op.create_index("ix_monetag_reward_events_telegram_id", "monetag_reward_events", ["telegram_id"])
    op.create_index("ix_monetag_reward_events_status", "monetag_reward_events", ["status"])
    op.create_index("ix_monetag_reward_events_expires_at", "monetag_reward_events", ["expires_at"])


def downgrade():
    op.drop_table("monetag_reward_events")
