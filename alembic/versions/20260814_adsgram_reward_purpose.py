"""Scope Adsgram reward sessions to their consuming game."""

from alembic import op
import sqlalchemy as sa


revision = "20260814_adsgram_purpose"
down_revision = "20260809_wall_rush"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "adsgram_reward_sessions",
        sa.Column("purpose", sa.String(30), server_default="WHEEL", nullable=False),
    )


def downgrade():
    op.drop_column("adsgram_reward_sessions", "purpose")
