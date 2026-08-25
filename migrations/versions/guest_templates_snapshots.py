"""Persist guest scenario templates and intro demo snapshots.

Expand-only migration: existing guest sessions remain valid because the
template relation is nullable for rows created before this migration.
"""

from alembic import op
import sqlalchemy as sa


revision = 'guest_templates_snapshots'
down_revision = 'guest_session_lifecycle'
branch_labels = None
depends_on = None


def _tables(bind):
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    bind = op.get_bind()
    tables = _tables(bind)
    if 'GuestTemplates' not in tables:
        op.create_table(
            'GuestTemplates',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('template_key', sa.String(80), nullable=False),
            sa.Column('session_type', sa.String(24), nullable=False),
            sa.Column('title', sa.String(180), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('config', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('template_key', name='uq_guest_template_key'),
        )
        op.create_index('ix_guest_template_key', 'GuestTemplates', ['template_key'])
        op.create_index('ix_guest_template_type', 'GuestTemplates', ['session_type'])
        op.create_index('ix_guest_template_active', 'GuestTemplates', ['is_active'])
    if 'GuestDemoSnapshots' not in tables:
        op.create_table(
            'GuestDemoSnapshots',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('session_id', sa.Integer(), sa.ForeignKey('GuestSessions.id', ondelete='CASCADE'), nullable=False),
            sa.Column('source_template_key', sa.String(80), nullable=False),
            sa.Column('source_template_version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('session_id', name='uq_guest_demo_snapshot_session'),
        )
        op.create_index('ix_guest_demo_snapshot_session', 'GuestDemoSnapshots', ['session_id'])
    if 'template_id' not in {c['name'] for c in sa.inspect(bind).get_columns('GuestSessions')}:
        op.add_column('GuestSessions', sa.Column('template_id', sa.Integer(), sa.ForeignKey('GuestTemplates.id'), nullable=True))
        op.create_index('ix_guest_session_template', 'GuestSessions', ['template_id'])


def downgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('GuestSessions')}
    if 'template_id' in columns:
        op.drop_index('ix_guest_session_template', table_name='GuestSessions')
        op.drop_column('GuestSessions', 'template_id')
    tables = _tables(bind)
    if 'GuestDemoSnapshots' in tables:
        op.drop_table('GuestDemoSnapshots')
    if 'GuestTemplates' in tables:
        op.drop_index('ix_guest_template_active', table_name='GuestTemplates')
        op.drop_index('ix_guest_template_type', table_name='GuestTemplates')
        op.drop_index('ix_guest_template_key', table_name='GuestTemplates')
        op.drop_table('GuestTemplates')
