"""Add private promotion banner metadata.

Revision ID: 20260719_promotion_banners
Revises: 20260719_promotions_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_promotion_banners"
down_revision = "20260719_promotions_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("promotions", sa.Column("banner_object_key", sa.String(500), nullable=True))
    op.add_column("promotions", sa.Column("banner_content_type", sa.String(50), nullable=True))
    op.add_column("promotions", sa.Column("banner_size", sa.Integer(), nullable=True))
    op.add_column("promotions", sa.Column("banner_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_promotions_banner_object_key", "promotions", ["banner_object_key"], unique=True)


def downgrade():
    op.drop_index("ix_promotions_banner_object_key", table_name="promotions")
    op.drop_column("promotions", "banner_updated_at")
    op.drop_column("promotions", "banner_size")
    op.drop_column("promotions", "banner_content_type")
    op.drop_column("promotions", "banner_object_key")
