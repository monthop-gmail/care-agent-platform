"""สายงานของการแสดงผล — ใบใหม่แทนใบเก่าในสายเดียวกัน (ADR-0016 ข้อ 5)

additive · แถวเดิมได้ `NULL` ซึ่งแปลว่า "ไม่มีใครแทนได้" ตรงกับพฤติกรรมเดิมทุกประการ
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_notification_stream"
down_revision = "0004_notification_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("care_notification", sa.Column("stream", sa.String(128), nullable=True))
    op.create_index(
        "ix_care_notif_stream", "care_notification", ["tenant_id", "stream", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_care_notif_stream", table_name="care_notification")
    op.drop_column("care_notification", "stream")
