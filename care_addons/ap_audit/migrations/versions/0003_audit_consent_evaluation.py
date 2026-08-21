"""audit: ผลการประเมินความยินยอมที่ถูกแช่แข็งไว้กับ event

Revision ID: 0003_audit_consent
Revises: 0002_audit_sequence
Create Date: 2026-08-21

event/v1 v1.4.0 เพิ่ม field `consent` — บ้านของ audit จริง ๆ สำหรับคำถาม
"อนุญาตด้วยใบไหน และเงื่อนไขผ่านตอนไหน" ซึ่งประเมินย้อนหลังไม่ได้หลังจากที่
consent/v1 v1.1.0 ทำให้ใบที่มี conditions ตอบตัวเองไม่ได้ (ADR-0016)

แถวเดิมได้ NULL = ไม่มีบันทึกการประเมิน ซึ่งตรงกับความจริงว่าตอนนั้นเรายังไม่ได้เก็บ
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_audit_consent"
down_revision = "0002_audit_sequence"
branch_labels = None
depends_on = None

TABLE = "ap_audit_event"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("consent", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, "consent")
