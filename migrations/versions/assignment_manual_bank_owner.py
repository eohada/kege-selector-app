"""Add personal ownership for manually authored bank tasks."""

from alembic import op
import sqlalchemy as sa


revision = 'assignment_manual_bank_owner'
down_revision = 'guest_snapshot_idx_contract'
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {column['name'] for column in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table):
    return {item['name'] for item in sa.inspect(bind).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    if 'created_by_id' not in _columns(bind, 'Tasks'):
        op.add_column('Tasks', sa.Column('created_by_id', sa.Integer(), nullable=True))
    if 'ix_Tasks_created_by_id' not in _indexes(bind, 'Tasks'):
        op.create_index('ix_Tasks_created_by_id', 'Tasks', ['created_by_id'])


def downgrade():
    bind = op.get_bind()
    if 'ix_Tasks_created_by_id' in _indexes(bind, 'Tasks'):
        op.drop_index('ix_Tasks_created_by_id', table_name='Tasks')
    if 'created_by_id' in _columns(bind, 'Tasks'):
        op.drop_column('Tasks', 'created_by_id')
