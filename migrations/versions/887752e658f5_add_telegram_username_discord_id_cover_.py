"""add telegram_username, discord_id, cover_url

Revision ID: 887752e658f5
Revises: 0002_oge_support
Create Date: 2026-03-30 21:45:00.713880

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '887752e658f5'
down_revision = '0002_oge_support'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = {t.lower(): t for t in inspector.get_table_names()}

    students_table = table_names.get('students')
    if students_table:
        cols = {c['name'].lower() for c in inspector.get_columns(students_table)}
        with op.batch_alter_table(students_table, schema=None) as batch_op:
            if 'telegram_username' not in cols:
                batch_op.add_column(sa.Column('telegram_username', sa.String(length=100), nullable=True))
            if 'discord_id' not in cols:
                batch_op.add_column(sa.Column('discord_id', sa.String(length=100), nullable=True))

    users_table = table_names.get('users')
    if users_table:
        cols = {c['name'].lower() for c in inspector.get_columns(users_table)}
        with op.batch_alter_table(users_table, schema=None) as batch_op:
            if 'cover_url' not in cols:
                batch_op.add_column(sa.Column('cover_url', sa.String(length=500), nullable=True))

def downgrade():
    with op.batch_alter_table('Users', schema=None) as batch_op:
        batch_op.drop_column('cover_url')

    with op.batch_alter_table('Students', schema=None) as batch_op:
        batch_op.drop_column('discord_id')
        batch_op.drop_column('telegram_username')
