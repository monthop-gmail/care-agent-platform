"""consent: เงื่อนไขที่ต้องยังเป็นจริงตอนเข้าถึง

Revision ID: 0002_consent_conditions
Revises: rls_ap_consent
Create Date: 2026-08-20

ใบยินยอมที่ตรวจแค่ตอนออกใบ จะยังใช้ได้แม้สถานการณ์เปลี่ยนไปแล้ว — เช่นหมอที่ลาออก
จากโรงพยาบาลไปแล้วแต่ใบยังไม่หมดอายุ (ADR-0010 ข้อ 4)

แถวเดิมได้ NULL = ไม่มีเงื่อนไข ซึ่งตรงกับความหมายเดิมของมันพอดี ไม่มีใบไหนเปลี่ยนความหมาย
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_consent_conditions"
down_revision = "rls_ap_consent"
branch_labels = None
depends_on = None

TABLE = "ap_consent_grant"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("conditions", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, "conditions")
