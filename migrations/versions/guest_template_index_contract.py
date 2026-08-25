"""Align guest template indexes with SQLAlchemy model contract."""

from alembic import op
import sqlalchemy as sa


revision = 'guest_template_index_contract'
down_revision = 'guest_templates_snapshots'
branch_labels = None
depends_on = None


def _indexes(bind, table):
    return {item['name'] for item in sa.inspect(bind).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    expected = {
        'GuestTemplates': {
            'ix_GuestTemplates_template_key': ['template_key'],
            'ix_GuestTemplates_session_type': ['session_type'],
            'ix_GuestTemplates_is_active': ['is_active'],
        },
        'GuestSessions': {
            'ix_GuestSessions_template_id': ['template_id'],
        },
    }
    for table, indexes in expected.items():
        existing = _indexes(bind, table)
        for name, columns in indexes.items():
            if name not in existing:
                op.create_index(name, table, columns)


def downgrade():
    bind = op.get_bind()
    expected = {
        'GuestSessions': ['ix_GuestSessions_template_id'],
        'GuestTemplates': ['ix_GuestTemplates_is_active', 'ix_GuestTemplates_session_type', 'ix_GuestTemplates_template_key'],
    }
    for table, indexes in expected.items():
        existing = _indexes(bind, table)
        for name in indexes:
            if name in existing:
                op.drop_index(name, table_name=table)
