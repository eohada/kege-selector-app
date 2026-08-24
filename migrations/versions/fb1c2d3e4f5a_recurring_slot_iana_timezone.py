"""Expand recurring lesson slots from legacy aliases to IANA time zones.

Revision ID: fb1c2d3e4f5a
Revises: fa0b1c2d3e4f
Create Date: 2026-08-20 18:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "fb1c2d3e4f5a"
down_revision = "fa0b1c2d3e4f"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower(): name for name in inspector.get_table_names()}
    table_name = tables.get("recurringlessonslots")
    if not table_name:
        return

    # Production installations can contain a stale inspector entry from an
    # earlier schema contract while the physical legacy table is already gone.
    # Verify the relation through PostgreSQL itself before issuing DDL/DML.
    # This migration is expand-only: a missing legacy table is a valid state.
    preparer = bind.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    qualified_table = f"{inspector.default_schema_name}.{quoted_table}"
    relation_exists = bind.execute(
        sa.text("SELECT to_regclass(:qualified_table)"),
        {"qualified_table": qualified_table},
    ).scalar()
    if relation_exists is None:
        return

    columns = {column["name"].lower(): column for column in inspector.get_columns(table_name)}
    timezone_column = columns.get("timezone")
    if not timezone_column:
        return

    if getattr(timezone_column["type"], "length", 0) and timezone_column["type"].length < 64:
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column("timezone", existing_type=timezone_column["type"], type_=sa.String(length=64))

    bind.execute(sa.text(f"UPDATE {quoted_table} SET timezone = 'Europe/Moscow' WHERE lower(timezone) = 'moscow'"))
    bind.execute(sa.text(f"UPDATE {quoted_table} SET timezone = 'Asia/Tomsk' WHERE lower(timezone) = 'tomsk'"))
    bind.execute(sa.text(f"UPDATE {quoted_table} SET timezone = 'Europe/Moscow' WHERE timezone IS NULL OR trim(timezone) = ''"))


def downgrade():
    # Expand-only: IANA values are intentionally preserved.
    pass
