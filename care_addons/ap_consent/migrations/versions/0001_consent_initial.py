"""consent initial — ap_consent_grant (idempotent adopt-safe)

Revision ID: 0001_consent_initial
Revises:
Create Date: 2026-08-19

── ทำไมต้อง idempotent ─────────────────────────────────────────────────────
ตาราง `ap_consent_grant` เคยถูกสร้างโดย migration ของ `ap_tenancy` (ไฟล์เดียวกับ
tenancy 3 ตาราง) ตอน consent ยังอยู่ในโมดูลนั้น · พอ tenancy ขึ้น kernel (pstack#3)
เราแยก consent ออกมาเป็นโมดูลของตัวเอง

- deployment เดิม → ตารางมีอยู่แล้วพร้อมคอลัมน์ครบ (ผ่าน consent_v1_alignment มาแล้ว)
  → **ข้าม create** แล้วให้ alembic บันทึก revision ให้เอง
- deploy ใหม่ → สร้างด้วยรูปร่างสุดท้ายเลย ไม่ต้องไล่ alter ตามประวัติเดิม

รูปแบบเดียวกับ initial migration ของ kernel `tenancy` ซึ่งออกแบบมาให้ adopt ได้
(docs/MODULE_GUIDE.md §9)

🔒 ไม่มีคอลัมน์ `status` โดยเจตนา — consent/v1 platform_rules ห้ามเก็บสถานะซ้ำ
   สถานะคำนวณจาก revoked_at / expires_at เท่านั้น
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_consent_initial"
down_revision = None
branch_labels = None
depends_on = None

TABLE = "ap_consent_grant"


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(TABLE):
        return  # adopt: ตารางมาจาก ap_tenancy เดิม — ไม่แตะ ปล่อยให้ alembic บันทึก revision

    op.create_table(
        TABLE,
        sa.Column("grant_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("subject_id", sa.String(63), nullable=False),
        sa.Column("grantee_type", sa.String(16), nullable=False),
        sa.Column("grantee_id", sa.String(63), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("granted_by_type", sa.String(16), nullable=False),
        sa.Column("granted_by_id", sa.String(63), nullable=False),
        sa.Column("authority_basis", sa.String(255), nullable=True),
        sa.Column("workspace_id", sa.String(63), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_type", sa.String(16), nullable=True),
        sa.Column("revoked_by_id", sa.String(63), nullable=True),
        sa.Column("revoked_reason", sa.String(255), nullable=True),
    )
    op.create_index("ix_ap_consent_grant_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_ap_consent_grant_subject_id", TABLE, ["subject_id"])
    op.create_index("ix_ap_consent_grant_grantee_id", TABLE, ["grantee_id"])
    op.create_index("ix_ap_consent_lookup", TABLE, ["tenant_id", "subject_id", "grantee_id"])


def downgrade() -> None:
    op.drop_table(TABLE)
