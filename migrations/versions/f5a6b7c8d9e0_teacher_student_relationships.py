"""Create the teacher/student relation required by registration and access checks.

Revision ID: f5a6b7c8d9e0
Revises: f4b5c6d7e8f9
Create Date: 2026-08-10 01:15:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "f5a6b7c8d9e0"
down_revision = "f4b5c6d7e8f9"
branch_labels = None
depends_on = None


def _table_name(existing_tables, expected_name):
    expected_lower = expected_name.lower()
    return next((name for name in existing_tables if name.lower() == expected_lower), None)


def _ensure_indexes(bind, table_name):
    indexes = {item['name'] for item in sa.inspect(bind).get_indexes(table_name)}
    if 'ix_teacher_students_teacher_id' not in indexes:
        op.create_index('ix_teacher_students_teacher_id', table_name, ['teacher_id'], unique=False)
    if 'ix_teacher_students_student_id' not in indexes:
        op.create_index('ix_teacher_students_student_id', table_name, ['student_id'], unique=False)
    if 'ix_teacher_student_unique' not in indexes:
        op.create_index('ix_teacher_student_unique', table_name, ['teacher_id', 'student_id'], unique=True)


def _backfill_links(bind, table_name, existing_tables):
    metadata = sa.MetaData()
    relation_table = sa.Table(table_name, metadata, autoload_with=bind)
    existing_pairs = {
        (row.teacher_id, row.student_id)
        for row in bind.execute(sa.select(relation_table.c.teacher_id, relation_table.c.student_id))
    }
    pairs = set()

    students_name = _table_name(existing_tables, 'Students')
    if students_name:
        students = sa.Table(students_name, metadata, autoload_with=bind)
        if {'mentor_id', 'user_id'}.issubset(students.c.keys()):
            pairs.update(
                (row.mentor_id, row.user_id)
                for row in bind.execute(
                    sa.select(students.c.mentor_id, students.c.user_id).where(students.c.mentor_id.is_not(None))
                )
            )

    enrollments_name = _table_name(existing_tables, 'Enrollments')
    if enrollments_name:
        enrollments = sa.Table(enrollments_name, metadata, autoload_with=bind)
        if {'tutor_id', 'student_id'}.issubset(enrollments.c.keys()):
            pairs.update(
                (row.tutor_id, row.student_id)
                for row in bind.execute(
                    sa.select(enrollments.c.tutor_id, enrollments.c.student_id).where(
                        enrollments.c.tutor_id.is_not(None),
                        enrollments.c.student_id.is_not(None),
                    )
                )
            )

    now = sa.func.now()
    for teacher_id, student_id in pairs:
        if not teacher_id or not student_id or teacher_id == student_id or (teacher_id, student_id) in existing_pairs:
            continue
        bind.execute(
            relation_table.insert().values(
                teacher_id=teacher_id,
                student_id=student_id,
                status='active',
                created_at=now,
                updated_at=now,
            )
        )


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    table_name = _table_name(existing_tables, 'teacher_students')

    if not table_name:
        op.create_table(
            'teacher_students',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('teacher_id', sa.Integer(), sa.ForeignKey('Users.id'), nullable=False),
            sa.Column('student_id', sa.Integer(), sa.ForeignKey('Users.id'), nullable=False),
            sa.Column('status', sa.String(length=30), nullable=False, server_default='active'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )
        table_name = 'teacher_students'

    _ensure_indexes(bind, table_name)
    _backfill_links(bind, table_name, existing_tables)


def downgrade():
    pass
