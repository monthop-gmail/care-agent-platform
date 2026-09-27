"""กำหนดตายของ notification — โดเมนตั้ง อุปกรณ์บังคับตาม (ADR-0016)

additive ทั้งสองคอลัมน์ · แถวเดิมอ่านได้เหมือนเดิม และช่องทางที่ไม่ใช่ TV ไม่สนใจค่านี้
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_notification_expiry"
down_revision = "0003_notification_presentation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "care_notification", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("care_notification", sa.Column("expiry_class", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("care_notification", "expiry_class")
    op.drop_column("care_notification", "expires_at")
