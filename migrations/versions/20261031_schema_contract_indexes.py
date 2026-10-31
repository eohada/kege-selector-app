"""Alembic migration: Add missing model indexes for schema contract compliance.

Revision ID: 20261031_schema_contract_indexes
Revises: 20261031_submission_attempt_data
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa

revision = "20261031_schema_contract_indexes"
down_revision = "20261031_submission_attempt_data"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower(): name for name in inspector.get_table_names()}

    # 1. LessonParticipantBans.ix_LessonParticipantBans_is_active
    tbl_bans = tables.get("lessonparticipantbans")
    if tbl_bans:
        existing_indexes = {ix["name"].lower() for ix in inspector.get_indexes(tbl_bans) if ix.get("name")}
        if "ix_lessonparticipantbans_is_active" not in existing_indexes:
            try:
                op.create_index(
                    "ix_LessonParticipantBans_is_active",
                    tbl_bans,
                    ["is_active"],
                )
            except Exception:
                pass

    # 2. RecurringLessonSlots: ix_RecurringLessonSlots_subject, ix_RecurringLessonSlots_series_id
    tbl_slots = tables.get("recurringlessonslots")
    if tbl_slots:
        existing_indexes = {ix["name"].lower() for ix in inspector.get_indexes(tbl_slots) if ix.get("name")}
        if "ix_recurringlessonslots_subject" not in existing_indexes:
            try:
                op.create_index(
                    "ix_RecurringLessonSlots_subject",
                    tbl_slots,
                    ["subject"],
                )
            except Exception:
                pass
        if "ix_recurringlessonslots_series_id" not in existing_indexes:
            try:
                op.create_index(
                    "ix_RecurringLessonSlots_series_id",
                    tbl_slots,
                    ["series_id"],
                )
            except Exception:
                pass


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower(): name for name in inspector.get_table_names()}

    tbl_bans = tables.get("lessonparticipantbans")
    if tbl_bans:
        existing_indexes = {ix["name"].lower() for ix in inspector.get_indexes(tbl_bans) if ix.get("name")}
        if "ix_lessonparticipantbans_is_active" in existing_indexes:
            try:
                op.drop_index("ix_LessonParticipantBans_is_active", table_name=tbl_bans)
            except Exception:
                pass

    tbl_slots = tables.get("recurringlessonslots")
    if tbl_slots:
        existing_indexes = {ix["name"].lower() for ix in inspector.get_indexes(tbl_slots) if ix.get("name")}
        if "ix_recurringlessonslots_subject" in existing_indexes:
            try:
                op.drop_index("ix_RecurringLessonSlots_subject", table_name=tbl_slots)
            except Exception:
                pass
        if "ix_recurringlessonslots_series_id" in existing_indexes:
            try:
                op.drop_index("ix_RecurringLessonSlots_series_id", table_name=tbl_slots)
            except Exception:
                pass
