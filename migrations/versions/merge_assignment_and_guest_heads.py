"""Merge the personal bank and guest diagnostic migration heads."""

from alembic import op


revision = "merge_assignment_guest_heads"
down_revision = ("assignment_manual_bank_owner", "guest_diagnostic_report")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
