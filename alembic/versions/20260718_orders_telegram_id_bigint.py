"""Widen orders.telegram_id from INTEGER to BIGINT.

Revision ID: 20260718_orders_tid_bigint
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_orders_tid_bigint"
down_revision = None
branch_labels = None
depends_on = None


def _column_type(bind):
    columns = sa.inspect(bind).get_columns("orders")
    column = next((item for item in columns if item["name"] == "telegram_id"), None)
    if column is None:
        raise RuntimeError("orders.telegram_id does not exist")
    return column["type"]


def _dependent_objects(bind):
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("orders") if item.get("name")}
    unique_constraints = {
        item["name"]
        for item in inspector.get_unique_constraints("orders")
        if item.get("name")
    }
    return indexes, unique_constraints


def upgrade():
    bind = op.get_bind()
    current_type = _column_type(bind)
    if isinstance(current_type, sa.BigInteger):
        return
    if not isinstance(current_type, sa.Integer):
        raise RuntimeError(
            f"orders.telegram_id must be INTEGER before migration; found {current_type}"
        )

    before = _dependent_objects(bind)
    op.alter_column(
        "orders",
        "telegram_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        postgresql_using="telegram_id::BIGINT",
    )
    after = _dependent_objects(bind)
    if after != before:
        raise RuntimeError("orders indexes or unique constraints changed during migration")


def downgrade():
    bind = op.get_bind()
    out_of_range = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM orders "
            "WHERE telegram_id > 2147483647 OR telegram_id < -2147483648)"
        )
    ).scalar()
    if out_of_range:
        raise RuntimeError("orders.telegram_id contains values outside INTEGER range")
    op.alter_column(
        "orders",
        "telegram_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="telegram_id::INTEGER",
    )
