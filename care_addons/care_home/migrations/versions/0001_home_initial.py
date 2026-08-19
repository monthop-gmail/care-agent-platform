"""home initial — care_home_item

Revision ID: 0001_home_initial
Revises:
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_home_initial"
down_revision = None
branch_labels = None
depends_on = None

TABLE = "care_home_item"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("item_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("patient_id", sa.String(63), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("home_location", sa.String(255), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_confirmed_by", sa.JSON(), nullable=True),
        sa.Column("set_aside_for", sa.Date(), nullable=True),
        sa.Column("set_aside_reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_care_home_item_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_care_home_item_patient_id", TABLE, ["patient_id"])
    op.create_index("ix_care_home_lookup", TABLE, ["tenant_id", "patient_id", "kind", "state"])


def downgrade() -> None:
    op.drop_table(TABLE)
