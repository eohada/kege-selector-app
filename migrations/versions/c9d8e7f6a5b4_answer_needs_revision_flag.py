"""add needs_revision flag to answers

Revision ID: c9d8e7f6a5b4
Revises: f1a2b3c4d5e6
Create Date: 2026-04-16 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c9d8e7f6a5b4"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("Answers") as batch_op:
        batch_op.add_column(sa.Column("needs_revision", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("Answers") as batch_op:
        batch_op.drop_column("needs_revision")
