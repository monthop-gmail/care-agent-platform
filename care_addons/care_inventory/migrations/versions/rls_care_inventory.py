"""เปิด RLS ให้ตารางของ care_inventory — ด่านที่สองตาม MODULE_GUIDE §9

Revision ID: rls_care_inventory
Revises: 0001_inventory_initial
Create Date: 2026-08-19

`scoped()` เป็นด่าน app ที่ตั้งใจ · RLS เป็นด่าน DB ที่กันตอนพลาด
policy อ่าน GUC `pstack.tenant_id` ที่ตั้งต่อ transaction — **ไม่ตั้ง = เห็น 0 แถว**
(deny by default) ดังนั้นทุก path ที่เปิด session เองต้องเรียก `core.tenancy.set_tenant()`
ก่อน query ไม่งั้นจะเงียบแทนที่จะพัง — ดู care-agent-platform#4

🔒 `rls_statements()` อยู่ **นอก guard has_table** เสมอ เพื่อให้ deployment ที่ adopt
   (ข้าม create_table) ได้ RLS ครบเหมือน deploy ใหม่ · คำสั่งเป็น idempotent สั่งซ้ำได้
"""

from alembic import op
from core.tenancy import rls_statements

revision = "rls_care_inventory"
down_revision = "0001_inventory_initial"
branch_labels = None
depends_on = None

TABLES = ['care_inventory_item']


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # sqlite ไม่มี RLS — scoped() ยังทำงานตามปกติ (architecture/stack.md)
    for table in TABLES:
        for statement in rls_statements(table):
            op.execute(statement)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
