"""orchestrator initial — care_daily_summary

Revision ID: 0001_orchestrator_initial
Revises:
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_orchestrator_initial"
down_revision = None
branch_labels = None
depends_on = None

TABLE = "care_daily_summary"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("summary_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("patient_id", sa.String(63), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("text", sa.String(4000), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipients", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "patient_id", "local_date", name="uq_care_daily_summary_day"),
    )
    op.create_index("ix_care_daily_summary_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_care_daily_summary_patient_id", TABLE, ["patient_id"])


def downgrade() -> None:
    op.drop_table(TABLE)
