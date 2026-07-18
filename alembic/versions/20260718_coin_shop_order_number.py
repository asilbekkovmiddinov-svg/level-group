"""Add unique public order number to Coin Shop orders.

Revision ID: 20260718_shop_order_no
Revises: 20260718_orders_tid_bigint
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_shop_order_no"
down_revision = "20260718_orders_tid_bigint"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("orders")}
    if "order_number" not in columns:
        op.add_column("orders", sa.Column("order_number", sa.String(8), nullable=True))
    op.execute(
        "WITH numbered AS ("
        "SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS position FROM orders"
        ") UPDATE orders SET order_number = "
        "LPAD((9999999 + numbered.position)::text, 8, '0') "
        "FROM numbered WHERE orders.id = numbered.id AND orders.order_number IS NULL"
    )
    op.alter_column("orders", "order_number", nullable=False)
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("orders")}
    if "ix_orders_order_number" not in indexes:
        op.create_index(
            "ix_orders_order_number",
            "orders",
            ["order_number"],
            unique=True,
        )
def downgrade():
    op.drop_index("ix_orders_order_number", table_name="orders")
    op.drop_column("orders", "order_number")
