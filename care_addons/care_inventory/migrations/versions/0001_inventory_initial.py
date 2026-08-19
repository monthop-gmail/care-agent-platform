"""inventory initial — care_inventory_item

Revision ID: 0001_inventory_initial
Revises:
Create Date: 2026-08-19

🔒 ไม่มีคอลัมน์ `expired` — สถานะหมดอายุคำนวณจาก `expires_on` เทียบวันนี้เสมอ
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_inventory_initial"
down_revision = None
branch_labels = None
depends_on = None

TABLE = "care_inventory_item"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("item_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("patient_id", sa.String(63), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("location", sa.String(255), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("opened_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recorded_by", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
    )
    op.create_index("ix_care_inventory_item_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_care_inventory_item_patient_id", TABLE, ["patient_id"])
    op.create_index("ix_care_inventory_item_normalized_name", TABLE, ["normalized_name"])
    op.create_index(
        "ix_care_inventory_lookup", TABLE, ["tenant_id", "patient_id", "normalized_name", "status"]
    )


def downgrade() -> None:
    op.drop_table(TABLE)
