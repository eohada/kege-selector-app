"""normalize legacy submission statuses

Revision ID: f1a2b3c4d5e6
Revises: 9f2b7c6e1a11
Create Date: 2026-04-16 17:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "9f2b7c6e1a11"
branch_labels = None
depends_on = None


def upgrade():
    # Canonical statuses:
    #   LATE -> SUBMITTED
    #   AUTO_GRADED -> GRADED
    op.execute(
        """
        UPDATE "Submissions"
        SET status = 'SUBMITTED', is_late = TRUE
        WHERE status = 'LATE'
        """
    )
    op.execute(
        """
        UPDATE "Submissions"
        SET status = 'GRADED'
        WHERE status = 'AUTO_GRADED'
        """
    )

    op.execute(
        """
        UPDATE "SubmissionAttempts"
        SET status = 'SUBMITTED'
        WHERE status = 'LATE'
        """
    )
    op.execute(
        """
        UPDATE "SubmissionAttempts"
        SET status = 'GRADED'
        WHERE status = 'AUTO_GRADED'
        """
    )


def downgrade():
    # Best-effort reverse mapping.
    op.execute(
        """
        UPDATE "Submissions"
        SET status = 'LATE'
        WHERE status = 'SUBMITTED' AND is_late = TRUE
        """
    )
    op.execute(
        """
        UPDATE "Submissions"
        SET status = 'AUTO_GRADED'
        WHERE status = 'GRADED'
        """
    )

    op.execute(
        """
        UPDATE "SubmissionAttempts"
        SET status = 'LATE'
        WHERE status = 'SUBMITTED'
        """
    )
    op.execute(
        """
        UPDATE "SubmissionAttempts"
        SET status = 'AUTO_GRADED'
        WHERE status = 'GRADED'
        """
    )
