"""add Arena ticket promocodes

Revision ID: 20260827_arena_ticket_promocodes
Revises: 20260827_bot_shop
"""
from alembic import op
import sqlalchemy as sa

revision = "20260827_arena_ticket_promocodes"
down_revision = "20260827_bot_shop"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "arena_ticket_promocodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("ticket_amount", sa.Integer(), nullable=False),
        sa.Column("usage_limit", sa.Integer(), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ticket_amount > 0", name="ck_arena_promocode_ticket_amount"),
        sa.CheckConstraint("usage_limit IS NULL OR usage_limit > 0", name="ck_arena_promocode_usage_limit"),
        sa.UniqueConstraint("code", name="uq_arena_ticket_promocodes_code"),
    )
    op.create_index("ix_arena_ticket_promocodes_code", "arena_ticket_promocodes", ["code"], unique=True)
    op.create_table(
        "arena_ticket_promocode_claims",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("promocode_id", sa.String(length=36), sa.ForeignKey("arena_ticket_promocodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("ticket_amount", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("promocode_id", "telegram_id", name="uq_arena_promocode_claim_user"),
    )
    op.create_index("ix_arena_ticket_promocode_claims_promocode_id", "arena_ticket_promocode_claims", ["promocode_id"])
    op.create_index("ix_arena_ticket_promocode_claims_telegram_id", "arena_ticket_promocode_claims", ["telegram_id"])


def downgrade():
    op.drop_index("ix_arena_ticket_promocode_claims_telegram_id", table_name="arena_ticket_promocode_claims")
    op.drop_index("ix_arena_ticket_promocode_claims_promocode_id", table_name="arena_ticket_promocode_claims")
    op.drop_table("arena_ticket_promocode_claims")
    op.drop_index("ix_arena_ticket_promocodes_code", table_name="arena_ticket_promocodes")
    op.drop_table("arena_ticket_promocodes")
