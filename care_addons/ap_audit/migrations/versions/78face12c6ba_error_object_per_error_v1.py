"""error becomes an object per error/v1

`event/v1` กำหนดให้ field `error` เป็น object ตาม `error/v1`
(code · category · message · retryable) ไม่ใช่ข้อความอิสระ — retry policy และ audit
ต้องตัดสินใจจาก category ได้โดยไม่ต้อง parse ข้อความ

ค่าเดิมที่เป็นข้อความอิสระถูกทิ้ง ไม่แปลง เพราะมันไม่เคย conform contract อยู่แล้ว
และเดา code/category ย้อนหลังให้ไม่ได้โดยไม่แต่งข้อมูลขึ้นเอง — ตัว event ยังอยู่ครบ
(append-only ไม่ถูกละเมิด) หายไปเฉพาะข้อความ error ที่ไม่ conform

Revision ID: 78face12c6ba
Revises: 878bdcfa69a1
"""
import sqlalchemy as sa
from alembic import op

revision = '78face12c6ba'
down_revision = '878bdcfa69a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # drop + add แทน alter type — Postgres ไม่มี implicit cast จาก text ไป json
    # และค่าเดิมไม่ใช่ JSON ที่ valid จึง cast ไม่ได้อยู่ดี
    op.drop_column('ap_audit_event', 'error')
    op.add_column('ap_audit_event', sa.Column('error', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('ap_audit_event', 'error')
    op.add_column('ap_audit_event', sa.Column('error', sa.TEXT(), nullable=True))
