"""Adsgram rewarded sessions."""

from alembic import op
import sqlalchemy as sa


revision = "20260726_adsgram_rewards"
down_revision = "20260719_coin_promotion_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "wheel_daily_limits",
        sa.Column("rewarded_ad_spins", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "adsgram_reward_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), server_default="PENDING", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_adsgram_reward_sessions_telegram_id", "adsgram_reward_sessions", ["telegram_id"])
    op.create_index("ix_adsgram_reward_sessions_token_hash", "adsgram_reward_sessions", ["token_hash"], unique=True)
    op.create_index("ix_adsgram_reward_sessions_status", "adsgram_reward_sessions", ["status"])
    op.create_index("ix_adsgram_reward_sessions_expires_at", "adsgram_reward_sessions", ["expires_at"])


def downgrade():
    op.drop_table("adsgram_reward_sessions")
    op.drop_column("wheel_daily_limits", "rewarded_ad_spins")
