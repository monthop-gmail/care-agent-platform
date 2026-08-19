"""careplan initial — care_careplan_task

Revision ID: 0001_careplan_initial
Revises:
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_careplan_initial"
down_revision = None
branch_labels = None
depends_on = None

TABLE = "care_careplan_task"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("task_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("patient_id", sa.String(63), nullable=False),
        sa.Column("task_type", sa.String(24), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("frequency", sa.JSON(), nullable=False),
        sa.Column("scheduled_times", sa.JSON(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("activated_by", sa.JSON(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at_appointment_id", sa.String(63), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.JSON(), nullable=True),
        sa.Column("source_document", sa.Text(), nullable=True),
        sa.Column("reminders_enabled", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_care_careplan_task_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_care_careplan_task_patient_id", TABLE, ["patient_id"])
    op.create_index("ix_care_careplan_patient", TABLE, ["tenant_id", "patient_id", "status"])


def downgrade() -> None:
    op.drop_table(TABLE)
