"""audit: ใช้ชื่อกลางของ event/v1 — sequence_no → sequence

Revision ID: 0004_audit_sequence_rename
Revises: 0003_audit_consent
Create Date: 2026-08-21

เราเพิ่ม `sequence_no` เองตอนเจอว่า trail เรียงไม่ได้บน Postgres แล้วเปิดเรื่องไว้ที่
agent-platform#23 · `event/v1` v1.3.0 รับเข้าเป็น `sequence` (ADR-0015) จึงย้ายมาใช้ชื่อกลาง
เพื่อไม่ต้องมีชั้นแปลชื่อระหว่างตารางกับ payload

⚠️ contract ย้ำว่า **ห้ามตีความช่องว่างว่ามีใบหาย** — ค่าของเราไม่ต่อเนื่องอยู่แล้วโดยตั้งใจ
"""

from alembic import op

revision = "0004_audit_sequence_rename"
down_revision = "0003_audit_consent"
branch_labels = None
depends_on = None

TABLE = "ap_audit_event"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("sequence_no", new_column_name="sequence")


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("sequence", new_column_name="sequence_no")
