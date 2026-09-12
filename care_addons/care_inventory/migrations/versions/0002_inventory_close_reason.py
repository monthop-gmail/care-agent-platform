"""เหตุผลตอนปิดรายการของใช้ — เก็บบนแถว ไม่ใช่ใน audit (ADR-0012)

Revision ID: 0002_inventory_close_reason
Revises: rls_care_inventory
Create Date: 2026-09-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_inventory_close_reason"
down_revision = "rls_care_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("care_inventory_item", sa.Column("close_reason", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("care_inventory_item", "close_reason")
