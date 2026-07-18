"""Add Referral V1 ledger tables.

Revision ID: 20260719_referral_v1
Revises: 20260718_shop_order_no
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_referral_v1"
down_revision = "20260718_shop_order_no"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "referral_profiles",
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("referral_code", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["telegram_id"], ["users.telegram_id"]),
        sa.PrimaryKeyConstraint("telegram_id"),
    )
    op.create_index(
        "ix_referral_profiles_referral_code",
        "referral_profiles",
        ["referral_code"],
        unique=True,
    )
    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("referrer_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("referred_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(255), nullable=True),
        sa.CheckConstraint(
            "referrer_telegram_id <> referred_telegram_id",
            name="ck_referrals_not_self",
        ),
        sa.ForeignKeyConstraint(["referred_telegram_id"], ["users.telegram_id"]),
        sa.ForeignKeyConstraint(["referrer_telegram_id"], ["users.telegram_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referred_telegram_id", name="uq_referrals_referred_user"),
    )
    op.create_index(
        "ix_referrals_referrer_telegram_id",
        "referrals",
        ["referrer_telegram_id"],
    )
    op.create_table(
        "referral_rewards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("referral_id", sa.Integer(), nullable=False),
        sa.Column("beneficiary_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("reward_type", sa.String(40), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["beneficiary_telegram_id"], ["users.telegram_id"]),
        sa.ForeignKeyConstraint(["referral_id"], ["referrals.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referral_id", "reward_type", name="uq_referral_reward_type"),
        sa.UniqueConstraint("transaction_id"),
    )
    op.create_index(
        "ix_referral_rewards_referral_id",
        "referral_rewards",
        ["referral_id"],
    )
    op.create_index(
        "ix_referral_rewards_beneficiary_telegram_id",
        "referral_rewards",
        ["beneficiary_telegram_id"],
    )


def downgrade():
    op.drop_index("ix_referral_rewards_beneficiary_telegram_id", table_name="referral_rewards")
    op.drop_index("ix_referral_rewards_referral_id", table_name="referral_rewards")
    op.drop_table("referral_rewards")
    op.drop_index("ix_referrals_referrer_telegram_id", table_name="referrals")
    op.drop_table("referrals")
    op.drop_index("ix_referral_profiles_referral_code", table_name="referral_profiles")
    op.drop_table("referral_profiles")
