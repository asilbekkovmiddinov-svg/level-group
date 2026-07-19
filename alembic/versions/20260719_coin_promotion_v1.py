"""coin shop promotion v1

Revision ID: 20260719_coin_promotion_v1
Revises: 20260719_internal_campaign_delivery
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_coin_promotion_v1"
down_revision = "20260719_internal_campaign_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "coin_promotions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("coin_package_id", sa.Integer(), nullable=False),
        sa.Column("original_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("promotion_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=False),
        sa.Column("reserved_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sold_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("per_user_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('DRAFT','ACTIVE','PAUSED','EXPIRED','DELETED')", name="ck_coin_promotions_status"),
        sa.CheckConstraint("original_price > 0", name="ck_coin_promotions_original_price"),
        sa.CheckConstraint("promotion_price > 0 AND promotion_price < original_price", name="ck_coin_promotions_price"),
        sa.CheckConstraint("total_quantity > 0", name="ck_coin_promotions_total_quantity"),
        sa.CheckConstraint("reserved_quantity >= 0", name="ck_coin_promotions_reserved_quantity"),
        sa.CheckConstraint("sold_quantity >= 0", name="ck_coin_promotions_sold_quantity"),
        sa.CheckConstraint("reserved_quantity + sold_quantity <= total_quantity", name="ck_coin_promotions_inventory"),
        sa.CheckConstraint("per_user_limit > 0", name="ck_coin_promotions_per_user_limit"),
        sa.CheckConstraint("end_at > start_at", name="ck_coin_promotions_schedule"),
        sa.ForeignKeyConstraint(["coin_package_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_coin_promotions_status", "coin_promotions", ["status"])
    op.create_index("ix_coin_promotions_coin_package_id", "coin_promotions", ["coin_package_id"])
    op.create_index("ix_coin_promotions_start_at", "coin_promotions", ["start_at"])
    op.create_index("ix_coin_promotions_end_at", "coin_promotions", ["end_at"])
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("locked_price", sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column("promotion_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancel_reason", sa.String(length=255), nullable=True))
    op.execute("UPDATE orders SET locked_price = price_uzs WHERE locked_price IS NULL")
    with op.batch_alter_table("orders") as batch:
        batch.alter_column("locked_price", existing_type=sa.Numeric(18, 2), nullable=False)
        batch.create_foreign_key("fk_orders_coin_promotion", "coin_promotions", ["promotion_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_orders_promotion_id", ["promotion_id"])
        batch.create_index("ix_orders_expires_at", ["expires_at"])


def downgrade():
    with op.batch_alter_table("orders") as batch:
        batch.drop_index("ix_orders_expires_at")
        batch.drop_index("ix_orders_promotion_id")
        batch.drop_constraint("fk_orders_coin_promotion", type_="foreignkey")
        batch.drop_column("cancel_reason")
        batch.drop_column("cancelled_at")
        batch.drop_column("expires_at")
        batch.drop_column("promotion_id")
        batch.drop_column("locked_price")
    op.drop_index("ix_coin_promotions_end_at", table_name="coin_promotions")
    op.drop_index("ix_coin_promotions_start_at", table_name="coin_promotions")
    op.drop_index("ix_coin_promotions_coin_package_id", table_name="coin_promotions")
    op.drop_index("ix_coin_promotions_status", table_name="coin_promotions")
    op.drop_table("coin_promotions")
