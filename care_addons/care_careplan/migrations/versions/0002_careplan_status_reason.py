"""เหตุผลที่คนพิมพ์ตอนเปลี่ยนสถานะคำสั่ง — เก็บบนแถว ไม่ใช่ใน audit

Revision ID: 0002_careplan_status_reason
Revises: rls_care_careplan
Create Date: 2026-09-12

ADR-0012 — erasure ตัดสะพานได้ก็ต่อเมื่อไม่มีเนื้อหาค้างอยู่ในที่ที่ลบไม่ได้
ประโยคที่ผู้ดูแลพิมพ์ตอนหยุดคำสั่งของหมอเคยอยู่ใน `transition.reason` ของ audit
ซึ่ง append-only · ย้ายมาอยู่บนแถวที่ลบได้ แล้วให้ event ชี้ด้วย subject_id แทน
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_careplan_status_reason"
down_revision = "rls_care_careplan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("care_careplan_task", sa.Column("status_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("care_careplan_task", "status_reason")
