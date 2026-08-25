"""Guest session lifecycle controls.

Adds audit timestamps for reopening a session and rotating its invite token.
The migration is expand-only and safe for an already deployed guest contour.
"""

from alembic import op
import sqlalchemy as sa


revision = "guest_session_lifecycle"
down_revision = "guest_contour_indexes"
branch_labels = None
depends_on = None


def _columns(bind):
    return {column["name"] for column in sa.inspect(bind).get_columns("GuestSessions")}


def upgrade():
    bind = op.get_bind()
    columns = _columns(bind)
    if "reopened_at" not in columns:
        op.add_column("GuestSessions", sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True))
    if "access_token_rotated_at" not in columns:
        op.add_column("GuestSessions", sa.Column("access_token_rotated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = _columns(bind)
    if "access_token_rotated_at" in columns:
        op.drop_column("GuestSessions", "access_token_rotated_at")
    if "reopened_at" in columns:
        op.drop_column("GuestSessions", "reopened_at")
