"""merge heads before timezone / UTC migration

Revision ID: mrg_apr25_tz_heads
Revises: c9d8e7f6a5b4, b2c3d4e5f6a7, d3e4f5a6b7c8
Create Date: 2026-04-25
"""

from alembic import op

revision = "mrg_apr25_tz_heads"
down_revision = ("c9d8e7f6a5b4", "b2c3d4e5f6a7", "d3e4f5a6b7c8")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
