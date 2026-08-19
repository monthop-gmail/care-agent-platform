"""safety initial — care_safety_event

Revision ID: 0001_safety_initial
Revises:
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_safety_initial"
down_revision = None
branch_labels = None
depends_on = None

TABLE = "care_safety_event"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("safety_event_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("patient_id", sa.String(63), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("escalated", sa.Boolean(), nullable=False),
        sa.Column("repeat_count", sa.Integer(), nullable=False),
        sa.Column("acknowledged_by", sa.JSON(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.String(255), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(63), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_care_safety_event_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_care_safety_event_patient_id", TABLE, ["patient_id"])
    op.create_index("ix_care_safety_event_correlation_id", TABLE, ["correlation_id"])
    op.create_index("ix_care_safety_dedup", TABLE, ["tenant_id", "patient_id", "kind", "observed_at"])


def downgrade() -> None:
    op.drop_table(TABLE)
