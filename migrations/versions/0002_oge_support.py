"""Add OGE support: document NEEDS_MANUAL_REVIEW status.

No schema changes required — Submission.status is already a String(50) column
that stores arbitrary status values. This migration serves as a documentation
checkpoint for the introduction of the NEEDS_MANUAL_REVIEW status and the
removal of hardcoded range(1, 28) fallbacks in favour of CourseTaskTemplate.

New status values for Submission.status (see app.constants.SubmissionStatus):
  ASSIGNED -> IN_PROGRESS -> SUBMITTED -> NEEDS_MANUAL_REVIEW -> GRADED
  GRADED -> RETURNED -> SUBMITTED (resubmit)

The OGE course data (ExamCourses, CourseTaskTemplates, GradingScales) is
populated via scripts/seed_oge_course.py rather than in this migration,
to keep migrations schema-only.

Revision ID: 0002_oge_support
Revises: 0001_initial
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_oge_support'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
