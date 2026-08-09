"""add read_minutes to theory blocks

Revision ID: 9f2b7c6e1a11
Revises: c0f4d9d2b9b1
Create Date: 2026-04-01 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f2b7c6e1a11"
down_revision = "c0f4d9d2b9b1"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'TheoryBlocks' not in set(inspector.get_table_names()):
        return
    columns = {column['name'] for column in inspector.get_columns('TheoryBlocks')}
    if 'read_minutes' in columns:
        return
    with op.batch_alter_table("TheoryBlocks") as batch_op:
        batch_op.add_column(sa.Column("read_minutes", sa.Integer(), nullable=False, server_default="5"))


def downgrade():
    with op.batch_alter_table("TheoryBlocks") as batch_op:
        batch_op.drop_column("read_minutes")
