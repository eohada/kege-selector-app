"""merge demo request metadata and telegram delivery heads

Revision ID: merge_demo_heads_20261005
Revises: demo_call_request_metadata, tg_delivery_contract_idx
"""
from alembic import op  # noqa: F401


revision = 'merge_demo_heads_20261005'
down_revision = ('demo_call_request_metadata', 'tg_delivery_contract_idx')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
