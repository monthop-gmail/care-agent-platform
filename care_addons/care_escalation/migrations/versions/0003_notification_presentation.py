"""presentation intent + presented_at บน care_notification (ADR-0014)

Revision ID: 0003_notification_presentation
Revises: rls_care_escalation
Create Date: 2026-09-27

`presentation` คือคำขอเชิงโครงสร้าง แยกจาก `text` เสมอ · `presented_at` อยู่ข้าง
delivery ไม่ใช่ข้าง evidence — "แสดงบนจอแล้ว" ไม่ใช่หลักฐานว่าคนเห็น
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_notification_presentation"
down_revision = "rls_care_escalation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("care_notification", sa.Column("presentation", sa.JSON(), nullable=True))
    op.add_column(
        "care_notification",
        sa.Column("presented_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("care_notification", "presented_at")
    op.drop_column("care_notification", "presentation")
