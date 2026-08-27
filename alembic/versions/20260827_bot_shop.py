"""Add idempotent EFC and Arena Ticket shop purchases."""

from alembic import op
import sqlalchemy as sa


revision = "20260827_bot_shop"
down_revision = "20260826_arena_v5"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("shop_settings"):
        op.create_table(
            "shop_settings",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("efc_price_uzs", sa.Numeric(18, 2), nullable=True),
            sa.Column("ticket_price_efc", sa.Numeric(18, 2), nullable=True),
            sa.Column("updated_by", sa.BigInteger(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["updated_by"], ["users.telegram_id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not inspector.has_table("shop_purchases"):
        op.create_table(
            "shop_purchases",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("telegram_id", sa.BigInteger(), nullable=False),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("purchase_type", sa.String(length=24), nullable=False),
            sa.Column("efc_amount", sa.Numeric(18, 2), nullable=True),
            sa.Column("ticket_quantity", sa.Integer(), nullable=True),
            sa.Column("uzs_cost", sa.Numeric(18, 2), nullable=True),
            sa.Column("efc_cost", sa.Numeric(18, 2), nullable=True),
            sa.Column("efc_price_uzs", sa.Numeric(18, 2), nullable=True),
            sa.Column("ticket_price_efc", sa.Numeric(18, 2), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "purchase_type IN ('EFC', 'ARENA_TICKET')",
                name="ck_shop_purchases_type",
            ),
            sa.CheckConstraint(
                "(purchase_type = 'EFC' AND efc_amount > 0 AND ticket_quantity IS NULL "
                "AND uzs_cost > 0 AND efc_cost IS NULL) OR "
                "(purchase_type = 'ARENA_TICKET' AND ticket_quantity > 0 "
                "AND efc_cost > 0 AND efc_amount IS NULL AND uzs_cost IS NULL)",
                name="ck_shop_purchases_payload",
            ),
            sa.ForeignKeyConstraint(["telegram_id"], ["users.telegram_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "idempotency_key", name="uq_shop_purchases_idempotency"
            ),
        )
        op.create_index(
            "ix_shop_purchases_telegram_id",
            "shop_purchases",
            ["telegram_id"],
        )
        op.create_index(
            "ix_shop_purchases_purchase_type",
            "shop_purchases",
            ["purchase_type"],
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("shop_purchases"):
        op.drop_table("shop_purchases")
    if inspector.has_table("shop_settings"):
        op.drop_table("shop_settings")
