"""Align the guest demo snapshot index with the ORM contract."""

from alembic import op
import sqlalchemy as sa


revision = 'guest_snapshot_idx_contract'
down_revision = 'guest_template_index_contract'
branch_labels = None
depends_on = None


def _indexes(bind, table):
    return {item['name'] for item in sa.inspect(bind).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    name = 'ix_GuestDemoSnapshots_session_id'
    if name not in _indexes(bind, 'GuestDemoSnapshots'):
        op.create_index(name, 'GuestDemoSnapshots', ['session_id'])


def downgrade():
    bind = op.get_bind()
    name = 'ix_GuestDemoSnapshots_session_id'
    if name in _indexes(bind, 'GuestDemoSnapshots'):
        op.drop_index(name, table_name='GuestDemoSnapshots')
