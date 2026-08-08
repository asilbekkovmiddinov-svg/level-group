"""Add production constraints for admin-managed coin packages."""

from alembic import op
import sqlalchemy as sa


revision = "20260808_coin_packages"
down_revision = "20260727_monetag_rewards"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint("ck_products_coins_amount_positive", "products", "coins_amount > 0")
    op.create_check_constraint("ck_products_price_positive", "products", "price_uzs > 0")
    op.create_index(
        "uq_products_scope_coin_amount",
        "products",
        [sa.text("upper(coalesce(platform, ''))"), sa.text("upper(coalesce(region, ''))"), "coins_amount"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_products_scope_coin_amount", table_name="products")
    op.drop_constraint("ck_products_price_positive", "products", type_="check")
    op.drop_constraint("ck_products_coins_amount_positive", "products", type_="check")
