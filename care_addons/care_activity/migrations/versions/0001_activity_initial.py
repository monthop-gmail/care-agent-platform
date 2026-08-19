"""activity initial — care_activity + care_activity_step

Revision ID: 0001_activity_initial
Revises:
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_activity_initial"
down_revision = None
branch_labels = None
depends_on = None

ACTIVITY = "care_activity"
STEP = "care_activity_step"


def upgrade() -> None:
    op.create_table(
        ACTIVITY,
        sa.Column("activity_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("patient_id", sa.String(63), nullable=False),
        sa.Column("activity_type", sa.String(24), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("context_checks", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(63), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_care_activity_tenant_id", ACTIVITY, ["tenant_id"])
    op.create_index("ix_care_activity_patient_id", ACTIVITY, ["patient_id"])
    op.create_index("ix_care_activity_correlation_id", ACTIVITY, ["correlation_id"])
    op.create_index("ix_care_activity_open", ACTIVITY, ["tenant_id", "patient_id", "state"])

    op.create_table(
        STEP,
        sa.Column("step_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("patient_id", sa.String(63), nullable=False),
        sa.Column(
            "activity_id",
            sa.String(63),
            sa.ForeignKey(f"{ACTIVITY}.activity_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("awaits_external_event", sa.String(64), nullable=True),
        sa.Column("stalled_after_minutes", sa.Integer(), nullable=False),
        sa.Column("care_job_id", sa.String(63), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stalled_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
    )
    op.create_index("ix_care_activity_step_tenant_id", STEP, ["tenant_id"])
    op.create_index("ix_care_activity_step_patient_id", STEP, ["patient_id"])
    op.create_index("ix_care_activity_step_activity_id", STEP, ["activity_id"])
    op.create_index("ix_care_activity_step_care_job_id", STEP, ["care_job_id"])
    op.create_index("ix_care_activity_step_order", STEP, ["tenant_id", "activity_id", "order"])


def downgrade() -> None:
    op.drop_table(STEP)
    op.drop_table(ACTIVITY)
