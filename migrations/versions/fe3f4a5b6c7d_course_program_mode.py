"""Store the complete study-mode configuration for an individual course.

Revision ID: fe3f4a5b6c7d
Revises: fd2e3f4a5b6c
"""
from alembic import op
import sqlalchemy as sa

revision = 'fe3f4a5b6c7d'
down_revision = 'fd2e3f4a5b6c'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = {name.lower(): name for name in inspector.get_table_names()}
    table = tables.get('courses')
    if not table:
        return
    columns = {column['name'].lower() for column in inspector.get_columns(table)}
    additions = [
        ('lessons_per_week', sa.Column('lessons_per_week', sa.Integer(), nullable=True)),
        ('lesson_duration_minutes', sa.Column('lesson_duration_minutes', sa.Integer(), nullable=True)),
        ('homework_hours_per_week', sa.Column('homework_hours_per_week', sa.Numeric(5, 2), nullable=True)),
        ('diagnostic_mode', sa.Column('diagnostic_mode', sa.String(length=30), nullable=True)),
        ('starting_forecast', sa.Column('starting_forecast', sa.Integer(), nullable=True)),
    ]
    with op.batch_alter_table(table) as batch:
        for name, column in additions:
            if name not in columns:
                batch.add_column(column)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    tables = {name.lower(): name for name in inspector.get_table_names()}
    table = tables.get('courses')
    if not table:
        return
    columns = {column['name'].lower() for column in inspector.get_columns(table)}
    with op.batch_alter_table(table) as batch:
        for name in ('starting_forecast', 'diagnostic_mode', 'homework_hours_per_week', 'lesson_duration_minutes', 'lessons_per_week'):
            if name in columns:
                batch.drop_column(name)
