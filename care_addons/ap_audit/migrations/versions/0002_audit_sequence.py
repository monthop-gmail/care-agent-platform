"""audit: ลำดับการเขียนสำหรับ event ที่เวลาเท่ากัน

Revision ID: 0002_audit_sequence
Revises: rls_ap_audit
Create Date: 2026-08-19

`occurred_at` อย่างเดียวเรียงไม่พอ — หลาย event ใน transaction เดียวมีเวลาเท่ากันได้
และ Postgres ไม่รับประกันลำดับของแถวที่ ORDER BY เท่ากัน · trail ที่เรียงไม่ได้
แปลว่าตอบไม่ได้ว่าอะไรเกิดก่อนอะไร ซึ่งเป็นเหตุผลทั้งหมดของการมี audit

แถวเดิมได้ค่า 0 — ของเก่ายังเรียงด้วยเวลาเหมือนเดิม ไม่มีแถวไหนถูกแก้ความหมาย
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_audit_sequence"
down_revision = "rls_ap_audit"
branch_labels = None
depends_on = None

TABLE = "ap_audit_event"


def upgrade() -> None:
    op.add_column(
        TABLE, sa.Column("sequence_no", sa.BigInteger(), nullable=False, server_default="0")
    )
    # ตัด server_default ทิ้งหลังแถวเดิมได้ค่าแล้ว — แถวใหม่ต้องได้ค่าจาก emit() เสมอ
    # ไม่ใช่จาก DB (ค่า 0 ที่เงียบ ๆ จะทำให้ลำดับผิดโดยไม่มีใครรู้)
    # batch mode เพราะ sqlite ไม่มี ALTER COLUMN — alembic จะสร้างตารางใหม่ให้แทน
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("sequence_no", server_default=None)


def downgrade() -> None:
    op.drop_column(TABLE, "sequence_no")
