"""consent: ย้ายค่าของโดเมนเข้ากล่อง params ตาม consent/v1 v1.1.0

Revision ID: 0003_conditions_params
Revises: 0002_consent_conditions
Create Date: 2026-08-21

รูปเดิมที่เรา ship ไปก่อนที่ contract จะรับ วางค่าของโดเมนเรียงข้าง `kind`:

    {"kind": "org_membership", "organization_id": "org-abc"}

รูปที่ contract รับ ให้ชั้นนอกสงวนไว้ให้ platform เพิ่ม field กลางทีหลังแบบ additive:

    {"kind": "org_membership", "params": {"organization_id": "org-abc"}}

🔒 ต้องแปลงข้อมูลเดิมด้วย ไม่ใช่แค่แก้โค้ด — ใบเก่าที่ยังเป็นรูปแบนจะถูกตัวตรวจ
   อ่าน `params` ไม่เจอแล้ว **ปฏิเสธการเข้าถึง** (fail closed) ซึ่งแปลว่าหมอที่ยัง
   ทำงานอยู่จะเข้าไม่ได้เงียบ ๆ ถ้าเราลืมแถวนี้
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0003_conditions_params"
down_revision = "0002_consent_conditions"
branch_labels = None
depends_on = None

TABLE = "ap_consent_grant"
RESERVED = {"kind", "params"}


def _reshape(conditions, *, to_params: bool):
    if not conditions:
        return conditions
    out = []
    for condition in conditions:
        if not isinstance(condition, dict):
            out.append(condition)
            continue
        if to_params:
            params = dict(condition.get("params") or {})
            params.update({k: v for k, v in condition.items() if k not in RESERVED})
            reshaped = {"kind": condition.get("kind")}
            if params:
                reshaped["params"] = params
        else:
            reshaped = {"kind": condition.get("kind"), **(condition.get("params") or {})}
        out.append(reshaped)
    return out


def _migrate(to_params: bool) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT grant_id, conditions FROM {TABLE} WHERE conditions IS NOT NULL")
    ).fetchall()
    for grant_id, conditions in rows:
        # sqlite คืน JSON เป็น string ส่วน Postgres คืนเป็น object แล้ว
        value = json.loads(conditions) if isinstance(conditions, str) else conditions
        reshaped = _reshape(value, to_params=to_params)
        if reshaped == value:
            continue
        bind.execute(
            sa.text(f"UPDATE {TABLE} SET conditions = :conditions WHERE grant_id = :grant_id"),
            {"conditions": json.dumps(reshaped, ensure_ascii=False), "grant_id": grant_id},
        )


def upgrade() -> None:
    _migrate(to_params=True)


def downgrade() -> None:
    _migrate(to_params=False)
