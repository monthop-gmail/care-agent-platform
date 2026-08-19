#!/usr/bin/env python3
"""พิสูจน์ว่า RLS กันข้าม tenant ได้จริง — **โดยไม่พึ่ง `scoped()`**

`scoped()` เป็นด่าน app ที่ตั้งใจ · RLS เป็นด่าน DB ที่กันตอนพลาด
เทสปกติของเราพิสูจน์ด่านแรกอยู่แล้ว (query ทุกตัวผ่าน `scoped()`) แต่ **พิสูจน์ด่านที่สองไม่ได้**
เพราะถ้า RLS ไม่ทำงานเลย เทสก็ยังเขียวหมด — สคริปต์นี้จึง query แบบดิบ ๆ ไม่มี WHERE tenant_id

ตรวจ 3 อย่าง:
  1. ตารางที่ควรมี RLS เปิดจริงและตั้ง FORCE (ไม่งั้น owner ข้ามได้)
  2. ตั้ง GUC เป็น tenant A แล้ว query ดิบ → เห็นเฉพาะของ A ไม่เห็นของ B
  3. ไม่ตั้ง GUC เลย → เห็น 0 แถว (deny by default ไม่ใช่เปิดหมด)

รัน:
    PSTACK_DATABASE_URL=postgresql+asyncpg://... python conformance/rls_check.py

ข้ามเองบน sqlite (ไม่มี RLS — architecture/stack.md)
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conformance._guard import require_destructive_consent

for candidate in (ROOT / "pstack_src", ROOT.parent / "pstack"):
    if (candidate / "addons").is_dir():
        os.environ.setdefault("PSTACK_ADDONS_PATHS", f"{candidate / 'addons'},care_addons")
        sys.path.insert(0, str(candidate))
        break

os.environ.setdefault("PSTACK_SECRET_KEY", "rls-check")
os.environ.setdefault(
    "PSTACK_MODULES",
    "users,tenancy,ap_consent,ap_audit,ap_policy,ap_approval,care_patient,care_escalation,"
    "care_routine,care_medication,care_journal,care_appointment,care_orientation,care_careplan,care_activity,care_inventory,care_home,care_safety,care_orchestrator",
)

# ตารางข้อมูลโดเมนที่ต้องมี RLS — เพิ่มตารางใหม่ที่มี tenant_id ต้องมาเพิ่มที่นี่ด้วย
PROTECTED = [
    "ap_audit_event",
    "ap_consent_grant",
    "ap_approval_request",
    "ap_approval",
    "care_patient",
    "care_caregiver",
    "care_team_member",
    "care_job",
    "care_notification",
    "care_daily_summary",
    "care_routine_item",
    "care_medication_version",
    "care_journal_entry",
    "care_appointment",
    "care_preparation_step",
    "care_careplan_task",
    "care_activity",
    "care_activity_step",
    "care_inventory_item",
    "care_home_item",
    "care_safety_event",
]

# ตารางที่ **ตั้งใจไม่เปิด RLS** — control plane ที่ต้องอ่านได้ก่อนจะรู้ว่าเป็น tenant ไหน
# (เหตุผลเดียวกับที่ kernel ไม่เปิด RLS บน tenant/workspace/tenant_member)
CONTROL_PLANE = ["care_line_binding", "care_line_pairing_code"]


async def main() -> int:
    import sqlalchemy as sa
    from addons.tenancy import services as kernel_tenancy
    from core.app import create_app
    from core.db import dispose_engine, get_engine, get_sessionmaker
    from core.registry import create_core_tables, sync_modules
    from core.runtime import ctx
    from core.tenancy import Principal, TenantScope, bind_tenant, unbind_tenant

    from care_addons.care_patient import services as patients

    logging.getLogger().setLevel(logging.WARNING)
    url = os.environ.get("PSTACK_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        print("ℹ ข้าม — ไม่ใช่ Postgres (sqlite ไม่มี RLS)")
        return 0

    require_destructive_consent("rls_check.py", url)

    create_app()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
        await conn.execute(sa.text("CREATE SCHEMA public"))
    await create_core_tables(engine)
    async with get_sessionmaker()() as bootstrap:
        await sync_modules(engine, bootstrap, ctx.load_order)

    failures: list[str] = []

    # (1) ตารางเปิด RLS + FORCE ครบไหม
    async with get_sessionmaker()() as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = ANY(:names)"
                ),
                {"names": PROTECTED + CONTROL_PLANE},
            )
        ).all()
    state = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in rows}
    for table in PROTECTED:
        enabled, forced = state.get(table, (False, False))
        if not enabled:
            failures.append(f"{table}: ไม่ได้เปิด RLS")
        elif not forced:
            failures.append(f"{table}: เปิด RLS แต่ไม่ได้ตั้ง FORCE — เจ้าของตารางจะข้ามได้")
    for table in CONTROL_PLANE:
        if state.get(table, (False, False))[0]:
            failures.append(
                f"{table}: เปิด RLS ทั้งที่เป็น control plane — จะหา tenant ของ LINE user ไม่เจอ"
            )

    # (2)(3) สร้างผู้ป่วยคนละ tenant แล้ว query ดิบ ๆ ไม่ผ่าน scoped()
    async with get_sessionmaker()() as session:
        made: dict[str, str] = {}
        for tenant_id in ("t-rls-a", "t-rls-b"):
            await kernel_tenancy.create_tenant(session, tenant_id, tenant_id)
            await session.commit()
            await bind_tenant(session, tenant_id)
            scope = TenantScope(
                tenant_id=tenant_id, principal=Principal(type="service", id="rls-check")
            )
            patient = await patients.create_patient(
                session, scope, display_name=f"ผู้ป่วยของ {tenant_id}"
            )
            await session.commit()
            made[tenant_id] = patient.patient_id

        raw = sa.text("SELECT patient_id FROM care_patient")   # ไม่มี WHERE tenant_id

        await bind_tenant(session, "t-rls-a")
        seen = {r[0] for r in (await session.execute(raw)).all()}
        if seen != {made["t-rls-a"]}:
            failures.append(
                f"query ดิบใน scope ของ t-rls-a เห็น {sorted(seen)} — ต้องเห็นเฉพาะ {made['t-rls-a']}"
            )

        await unbind_tenant(session)
        await session.commit()   # ปิด transaction เดิม (GUC ติดอยู่กับ transaction นั้น)
        no_scope = (await session.execute(raw)).all()
        if no_scope:
            failures.append(
                f"ไม่ได้ตั้ง scope แต่ยังเห็น {len(no_scope)} แถว — ต้อง deny by default"
            )

        # (4) worker ต้องหารายชื่อ tenant ได้ **โดยไม่มี GUC** ไม่งั้นมันจะไม่รู้ว่าต้องทำงานให้ใคร
        #     แล้วเงียบสนิทโดยไม่มี error — เจอจริงตอนเปิด RLS รอบแรก (worker อ่านจาก care_job
        #     ซึ่งมี RLS จึงได้ 0 tenant เสมอ) ตอนนี้อ่านจากตาราง tenant ของ kernel ที่ไม่มี RLS
        discoverable = (await session.execute(sa.text("SELECT tenant_id FROM tenant"))).all()
        if len(discoverable) < 2:
            failures.append(
                "อ่านรายชื่อ tenant โดยไม่มี GUC ไม่ได้ — background worker จะไม่รู้ว่าต้องทำงานให้ใคร"
            )

    await dispose_engine()

    for failure in failures:
        print(f"   {failure}")
    if failures:
        print(f"\n✗ RLS ไม่ผ่าน — {len(failures)} ข้อ")
        return 1
    print(
        f"✓ RLS ผ่าน — {len(PROTECTED)} ตารางเปิด FORCE ครบ · "
        f"query ดิบข้าม tenant เห็นเฉพาะของตัวเอง · ไม่ตั้ง scope เห็น 0 แถว"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
