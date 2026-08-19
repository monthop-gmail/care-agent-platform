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

# ตารางเดิมเคยมี FK ไป ap_tenant (ตอน consent ยังอยู่ใน ap_tenancy ข้าง ๆ ตาราง tenant)
# หลัง rename ตาราง FK นั้นจะชี้ไป `tenant` ของ kernel พร้อม ondelete CASCADE ติดมาด้วย
# ขณะที่ deploy ใหม่ไม่มี FK → พฤติกรรมตอนลบ tenant จะต่างกันระหว่าง fresh กับ adopt
LEGACY_FK_TARGETS = {"tenant", "ap_tenant"}


def _drop_legacy_tenant_fk(insp) -> None:
    """ทำให้ deployment ที่ adopt เท่ากับ deploy ใหม่ — ไม่มี FK ไปตารางของ kernel

    ไม่มีตารางโดเมนไหนใน repo นี้ผูก FK กับ tenant เลย (ทุกตัวถือ tenant_id เป็น string เฉย ๆ)
    consent มี FK ติดมาเพราะเคยอยู่ในโมดูลเดียวกับตาราง tenant เท่านั้น — และการผูก FK
    ข้ามโมดูลไปหาตารางที่ **kernel เป็นเจ้าของ** ทำให้ลำดับการติดตั้ง/ถอนโมดูลผูกกันโดยไม่จำเป็น
    """
    if op.get_bind().dialect.name != "postgresql":
        return  # sqlite ไม่มี adopt path จริง และ drop constraint ไม่ได้ตรง ๆ อยู่แล้ว
    for fk in insp.get_foreign_keys(TABLE):
        if fk.get("referred_table") in LEGACY_FK_TARGETS and fk.get("name"):
            op.drop_constraint(fk["name"], TABLE, type_="foreignkey")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table(TABLE):
        # adopt: ตารางมาจาก ap_tenancy เดิม — ไม่สร้างใหม่ แต่ต้องเก็บ FK ที่ตกค้างให้เท่ากับ fresh
        _drop_legacy_tenant_fk(insp)
        return

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
