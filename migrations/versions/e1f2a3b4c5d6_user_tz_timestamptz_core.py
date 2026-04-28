"""User timezone fields; core tables TIMESTAMP WITH TIME ZONE (Moscow-naive -> UTC).

Revision ID: e1f2a3b4c5d6
Revises: mrg_apr25_tz_heads
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa


revision = "e1f2a3b4c5d6"
down_revision = "mrg_apr25_tz_heads"
branch_labels = None
depends_on = None


def _pg_tz(col: str) -> str:
    return (
        f"CASE WHEN {col} IS NULL THEN NULL ELSE {col} AT TIME ZONE 'Europe/Moscow' END"
    )


def upgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name

    with op.batch_alter_table("Users") as batch_op:
        batch_op.add_column(
            sa.Column("timezone_mode", sa.String(length=16), nullable=False, server_default="auto")
        )
        batch_op.add_column(sa.Column("timezone_iana", sa.String(length=64), nullable=True))

    if dialect != "postgresql":
        return

    stmts = [
        f'ALTER TABLE "Users" ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("created_at")})',
        f'ALTER TABLE "Users" ALTER COLUMN last_login TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("last_login")})',
        f'ALTER TABLE "Users" ALTER COLUMN presence_last_seen_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("presence_last_seen_at")})',
        f'ALTER TABLE "Users" ALTER COLUMN presence_updated_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("presence_updated_at")})',
        f'ALTER TABLE "Assignments" ALTER COLUMN deadline TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("deadline")})',
        f'ALTER TABLE "Assignments" ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("created_at")})',
        f'ALTER TABLE "Assignments" ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("updated_at")})',
        f'ALTER TABLE "Submissions" ALTER COLUMN assigned_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("assigned_at")})',
        f'ALTER TABLE "Submissions" ALTER COLUMN started_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("started_at")})',
        f'ALTER TABLE "Submissions" ALTER COLUMN submitted_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("submitted_at")})',
        f'ALTER TABLE "Submissions" ALTER COLUMN graded_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("graded_at")})',
        f'ALTER TABLE "Submissions" ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("created_at")})',
        f'ALTER TABLE "Submissions" ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("updated_at")})',
        f'ALTER TABLE "Answers" ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("created_at")})',
        f'ALTER TABLE "Answers" ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("updated_at")})',
        f'ALTER TABLE "Answers" ALTER COLUMN submitted_separately_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("submitted_separately_at")})',
        f'ALTER TABLE "Answers" ALTER COLUMN student_code_saved_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("student_code_saved_at")})',
        f'ALTER TABLE "Lessons" ALTER COLUMN lesson_date TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("lesson_date")})',
        f'ALTER TABLE "Lessons" ALTER COLUMN published_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("published_at")})',
        f'ALTER TABLE "Lessons" ALTER COLUMN started_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("started_at")})',
        f'ALTER TABLE "Lessons" ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("created_at")})',
        f'ALTER TABLE "Lessons" ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("updated_at")})',
        'ALTER TABLE analytics_events ALTER COLUMN "timestamp" TYPE TIMESTAMP WITH TIME ZONE USING '
        + f"({_pg_tz('timestamp')})",
        f'ALTER TABLE user_mastery ALTER COLUMN last_practiced_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("last_practiced_at")})',
        f'ALTER TABLE user_mastery ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("updated_at")})',
        f'ALTER TABLE user_task_mmr ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("updated_at")})',
        f'ALTER TABLE rematch_queue ALTER COLUMN due_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("due_at")})',
        f'ALTER TABLE rematch_queue ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("created_at")})',
        f'ALTER TABLE rematch_queue ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("updated_at")})',
        f'ALTER TABLE "SubmissionAttempts" ALTER COLUMN submitted_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("submitted_at")})',
        f'ALTER TABLE "SubmissionAttempts" ALTER COLUMN graded_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("graded_at")})',
        f'ALTER TABLE "SubmissionComments" ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("created_at")})',
        f'ALTER TABLE "SubmissionCommentThreadReads" ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("updated_at")})',
        f'ALTER TABLE "SubmissionTelegramDeadlineSents" ALTER COLUMN sent_at TYPE TIMESTAMP WITH TIME ZONE USING ({_pg_tz("sent_at")})',
    ]
    for sql in stmts:
        op.execute(sql)

    with op.batch_alter_table("Users") as batch_op:
        batch_op.alter_column("timezone_mode", server_default=None)


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        raise NotImplementedError("UTC timestamptz downgrade not supported")
    with op.batch_alter_table("Users") as batch_op:
        batch_op.drop_column("timezone_iana")
        batch_op.drop_column("timezone_mode")
