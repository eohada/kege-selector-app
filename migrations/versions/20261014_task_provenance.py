"""Add task provenance and global reuse metadata.

Revision ID: task_provenance_20261014
Revises: v2_schema_contract_20261013
Create Date: 2026-10-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
import calendar
from datetime import datetime, timedelta, timezone


revision = 'task_provenance_20261014'
down_revision = 'v2_schema_contract_20261013'
branch_labels = None
depends_on = None


def _resolve_table_name(table_names, expected_name):
    return next((name for name in table_names if name.lower() == expected_name.lower()), None)


def _add_calendar_months(value, months=2):
    if value is None:
        return None
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def _naive_moscow(value):
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone(timedelta(hours=3))).replace(tzinfo=None)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = _resolve_table_name(inspector.get_table_names(), 'Tasks')
    if not table_name:
        return

    columns = {column['name'].lower() for column in inspector.get_columns(table_name)}
    columns_to_add = (
        ('source_name', sa.String(length=160), True, None),
        ('source_year', sa.SmallInteger(), True, None),
        ('source_task_number', sa.SmallInteger(), True, None),
        ('exam_year', sa.SmallInteger(), True, None),
        ('source_key', sa.String(length=190), True, None),
        ('content_fingerprint', sa.String(length=64), True, None),
        ('prototype_status', sa.String(length=20), False, "'unreviewed'"),
        ('ingest_status', sa.String(length=20), False, "'ready'"),
    )
    for name, column_type, nullable, server_default in columns_to_add:
        if name.lower() in columns:
            continue
        column = sa.Column(
            name,
            column_type,
            nullable=nullable,
            server_default=sa.text(server_default) if server_default is not None else None,
        )
        op.add_column(table_name, column)

    indexes = (
        ('ix_Tasks_source_year', ['source_year'], False),
        ('ix_Tasks_source_task_number', ['source_task_number'], False),
        ('ix_Tasks_exam_year', ['exam_year'], False),
        ('ix_Tasks_source_key', ['source_key'], True),
        ('ix_Tasks_content_fingerprint', ['content_fingerprint'], False),
        ('ix_Tasks_prototype_status', ['prototype_status'], False),
        ('ix_Tasks_ingest_status', ['ingest_status'], False),
    )
    existing_indexes = {index['name'].lower() for index in sa.inspect(bind).get_indexes(table_name) if index.get('name')}
    for name, columns, unique in indexes:
        if name.lower() in existing_indexes:
            continue
        column_sql = ', '.join(f'"{column}"' for column in columns)
        uniqueness = 'UNIQUE ' if unique else ''
        op.execute(sa.text(f'CREATE {uniqueness}INDEX IF NOT EXISTS "{name}" ON "{table_name}" ({column_sql})'))

    inspector = sa.inspect(bind)
    for expected_table in ('LessonTasks', 'AssignmentTasks'):
        real_table = _resolve_table_name(inspector.get_table_names(), expected_table)
        if not real_table:
            continue
        existing_columns = {column['name'].lower() for column in inspector.get_columns(real_table)}
        if 'is_error_review' not in existing_columns:
            op.add_column(
                real_table,
                sa.Column('is_error_review', sa.Boolean(), nullable=False, server_default=sa.false()),
            )

    inspector = sa.inspect(bind)
    seen_table = _resolve_table_name(inspector.get_table_names(), 'StudentTaskSeen')
    if seen_table:
        seen_columns = {column['name'].lower() for column in inspector.get_columns(seen_table)}
        seen_additions = (
            # Add nullable, backfill from the original exposure time, then enforce NOT NULL.
            ('last_seen_at', sa.DateTime(), True, None),
            ('expires_at', sa.DateTime(), True, None),
            ('normal_use_count', sa.Integer(), False, '1'),
            ('expired_reuse_count', sa.Integer(), False, '0'),
            ('error_review_count', sa.Integer(), False, '0'),
            ('last_error_review_at', sa.DateTime(), True, None),
            ('context_id', sa.String(length=96), True, None),
        )
        for name, column_type, nullable, server_default in seen_additions:
            if name.lower() in seen_columns:
                continue
            column = sa.Column(
                name,
                column_type,
                nullable=nullable,
                server_default=sa.text(server_default) if server_default is not None else None,
            )
            op.add_column(seen_table, column)

        current_indexes = {index['name'].lower() for index in sa.inspect(bind).get_indexes(seen_table) if index.get('name')}
        if 'ix_studenttaskseen_last_seen_at' not in current_indexes:
            op.create_index('ix_StudentTaskSeen_last_seen_at', seen_table, ['last_seen_at'])
        if 'ix_studenttaskseen_expires_at' not in current_indexes:
            op.create_index('ix_StudentTaskSeen_expires_at', seen_table, ['expires_at'])

        seen = sa.Table(seen_table, sa.MetaData(), autoload_with=bind)
        for row in bind.execute(sa.select(seen.c.id, seen.c.created_at, seen.c.last_seen_at, seen.c.expires_at)).mappings():
            last_seen = row['last_seen_at'] or row['created_at'] or datetime.utcnow()
            expires = row['expires_at'] or _add_calendar_months(last_seen)
            bind.execute(
                seen.update().where(seen.c.id == row['id']).values(last_seen_at=last_seen, expires_at=expires)
            )
        if 'last_seen_at' in seen.c and seen.c.last_seen_at.nullable:
            with op.batch_alter_table(seen_table) as batch_op:
                batch_op.alter_column('last_seen_at', existing_type=sa.DateTime(), nullable=False)

        # Reconstruct recent assignment and lesson exposures so the rule takes effect
        # immediately after migration, including work assigned before this revision.
        table_names = set(sa.inspect(bind).get_table_names())
        required_tables = ('Submissions', 'AssignmentTasks', 'Assignments', 'LessonTasks', 'Lessons')
        resolved = {name: _resolve_table_name(table_names, name) for name in required_tables}
        if all(resolved.values()):
            meta = sa.MetaData()
            tables = {name: sa.Table(table_name, meta, autoload_with=bind) for name, table_name in resolved.items()}
            events = []
            submissions = tables['Submissions']
            assignment_tasks = tables['AssignmentTasks']
            assignments = tables['Assignments']
            lesson_tasks = tables['LessonTasks']
            lessons = tables['Lessons']
            assignment_rows = bind.execute(
                sa.select(
                    submissions.c.student_id,
                    assignment_tasks.c.task_id,
                    submissions.c.assigned_at,
                    assignments.c.assignment_type,
                    assignment_tasks.c.is_error_review,
                    assignments.c.assignment_id,
                )
                .select_from(
                    submissions.join(assignment_tasks, submissions.c.assignment_id == assignment_tasks.c.assignment_id)
                    .join(assignments, assignments.c.assignment_id == submissions.c.assignment_id)
                )
            ).mappings()
            for row in assignment_rows:
                if row['student_id'] is not None and row['task_id'] is not None and row['assigned_at'] is not None:
                    is_error_review = bool(row.get('is_error_review')) or str(row.get('assignment_type') or '').lower() in {'error_review', 'mistakes_review', 'wrong_answers'}
                    events.append((row['student_id'], row['task_id'], _naive_moscow(row['assigned_at']), is_error_review, f"assignment:{row['assignment_id']}", row['assignment_id']))

            lesson_rows = bind.execute(
                sa.select(
                    lessons.c.student_id,
                    lesson_tasks.c.task_id,
                    lesson_tasks.c.date_assigned,
                    lesson_tasks.c.assignment_type,
                    lesson_tasks.c.is_error_review,
                    lesson_tasks.c.lesson_task_id,
                )
                .select_from(lesson_tasks.join(lessons, lesson_tasks.c.lesson_id == lessons.c.lesson_id))
                .where(lessons.c.student_id.is_not(None), lesson_tasks.c.is_visible_to_student.is_(True))
            ).mappings()
            for row in lesson_rows:
                event_time = row['date_assigned']
                if row['student_id'] is not None and row['task_id'] is not None and event_time is not None:
                    is_error_review = bool(row.get('is_error_review')) or str(row.get('assignment_type') or '').lower() in {'error_review', 'mistakes_review', 'wrong_answers'}
                    events.append((row['student_id'], row['task_id'], _naive_moscow(event_time), is_error_review, f"lesson:{row['lesson_task_id']}", row['lesson_task_id']))

            events.sort(key=lambda item: item[2])
            deduplicated_events = []
            event_keys = set()
            for item in events:
                event_key = (item[0], item[1], item[4])
                if event_key not in event_keys:
                    deduplicated_events.append(item)
                    event_keys.add(event_key)

            seen_rows = {
                (row['student_id'], row['task_id']): row
                for row in bind.execute(sa.select(seen)).mappings()
            }
            for student_id, task_id, exposed_at, is_error_review, source, context_id in deduplicated_events:
                key = (student_id, task_id)
                existing = seen_rows.get(key)
                if existing is None:
                    values = {
                        'student_id': student_id,
                        'task_id': task_id,
                        'source': source[:40],
                        'created_at': exposed_at,
                        'last_seen_at': exposed_at,
                        'expires_at': None if is_error_review else _add_calendar_months(exposed_at),
                        'normal_use_count': 0 if is_error_review else 1,
                        'expired_reuse_count': 0,
                        'error_review_count': 1 if is_error_review else 0,
                        'last_error_review_at': exposed_at if is_error_review else None,
                        'context_id': str(context_id)[:96],
                    }
                    result = bind.execute(seen.insert().values(**values))
                    values['id'] = result.inserted_primary_key[0]
                    seen_rows[key] = values
                    continue

                if is_error_review:
                    bind.execute(seen.update().where(seen.c.id == existing['id']).values(
                        error_review_count=int(existing.get('error_review_count') or 0) + 1,
                        last_error_review_at=max(existing.get('last_error_review_at') or exposed_at, exposed_at),
                    ))
                    existing['error_review_count'] = int(existing.get('error_review_count') or 0) + 1
                    continue

                latest = max(existing.get('last_seen_at') or exposed_at, exposed_at)
                current_expiry = existing.get('expires_at')
                normal_count = int(existing.get('normal_use_count') or 0)
                expired_count = int(existing.get('expired_reuse_count') or 0)
                if normal_count and current_expiry and exposed_at >= current_expiry:
                    expired_count += 1
                bind.execute(seen.update().where(seen.c.id == existing['id']).values(
                    last_seen_at=latest,
                    expires_at=max(current_expiry or _add_calendar_months(exposed_at), _add_calendar_months(exposed_at)),
                    normal_use_count=max(1, normal_count + 1),
                    expired_reuse_count=expired_count,
                    source=source[:40],
                    context_id=str(context_id)[:96],
                ))
                existing['last_seen_at'] = latest
                existing['expires_at'] = max(current_expiry or _add_calendar_months(exposed_at), _add_calendar_months(exposed_at))
                existing['normal_use_count'] = max(1, normal_count + 1)
                existing['expired_reuse_count'] = expired_count


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_table = _resolve_table_name(inspector.get_table_names(), 'Tasks')
    task_indexes = {
        'ix_tasks_source_year',
        'ix_tasks_source_task_number',
        'ix_tasks_exam_year',
        'ix_tasks_source_key',
        'ix_tasks_content_fingerprint',
        'ix_tasks_prototype_status',
        'ix_tasks_ingest_status',
    }
    task_columns = (
        'source_name', 'source_year', 'source_task_number', 'exam_year',
        'source_key', 'content_fingerprint', 'prototype_status', 'ingest_status',
    )

    def drop_indexes(table_name, expected_names):
        for index in sa.inspect(bind).get_indexes(table_name):
            if (index.get('name') or '').lower() in expected_names:
                op.drop_index(index['name'], table_name=table_name)

    def drop_columns(table_name, expected_names):
        columns = {column['name'].lower(): column['name'] for column in sa.inspect(bind).get_columns(table_name)}
        present = [columns[name.lower()] for name in expected_names if name.lower() in columns]
        if present:
            with op.batch_alter_table(table_name) as batch_op:
                for name in present:
                    batch_op.drop_column(name)

    if task_table:
        drop_indexes(task_table, task_indexes)
        drop_columns(task_table, task_columns)

    for expected_table in ('LessonTasks', 'AssignmentTasks'):
        table_name = _resolve_table_name(sa.inspect(bind).get_table_names(), expected_table)
        if table_name:
            drop_columns(table_name, ('is_error_review',))

    seen_table = _resolve_table_name(sa.inspect(bind).get_table_names(), 'StudentTaskSeen')
    if seen_table:
        drop_indexes(seen_table, {
            'ix_studenttaskseen_last_seen_at',
            'ix_studenttaskseen_expires_at',
        })
        drop_columns(seen_table, (
            'last_seen_at', 'expires_at', 'normal_use_count', 'expired_reuse_count',
            'error_review_count', 'last_error_review_at', 'context_id',
        ))
