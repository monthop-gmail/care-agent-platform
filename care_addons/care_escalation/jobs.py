"""Periodic job — เดิน closed loop ทุกนาทีผ่าน ARQ worker

ต่างจาก tick endpoint ตรงที่วนทุก tenant ที่มีงานค้าง และไม่ต้องมีใครมาเรียก

⏰ cron ของ pstack ตีความด้วยเวลา UTC ของ container — ที่นี่ไม่ต้องแปลงอะไร
   เพราะ due time ของทุก job ถูกคำนวณเป็น UTC ตั้งแต่ตอน materialize แล้ว
   (timezone ของผู้ป่วยถูกใช้ตอนแปลง "08:00 ตามเวลาไทย" เป็น UTC เท่านั้น)
"""

from __future__ import annotations

import logging
from typing import Any

from addons.tenancy.models import Tenant
from core.db import get_sessionmaker
from core.jobs import periodic_job
from core.tenancy import Principal, TenantScope, bind_tenant, unbind_tenant
from sqlalchemy import select

from care_addons.care_escalation import services as svc

logger = logging.getLogger(__name__)

SYSTEM_PRINCIPAL = Principal(type="service", id="care-orchestrator", display_name="Care Orchestrator")


@periodic_job(minute=set(range(60)))   # ทุกนาที — ต้องการ pstack >= v0.2.0
async def care_tick(ctx: Any) -> dict:
    """เดิน closed loop ให้ทุก tenant ที่มีงานค้าง

    🔒 **หนึ่ง tenant = หนึ่ง transaction** — RLS อ่าน GUC ที่มีอายุแค่ใน transaction
       ถ้ารวมทุก tenant ไว้ transaction เดียว จะตั้ง GUC ให้ tenant ไหนก็ผิดกับที่เหลือ
       (care-agent-platform#4)
    """
    totals = {"reminded": 0, "missed": 0, "escalated": 0, "deferred": 0}
    async with get_sessionmaker()() as session:
        # 🔒 หารายชื่อ tenant จากตาราง control plane ของ kernel ไม่ใช่จาก care_job
        #
        #    care_job เปิด RLS ไว้ → คิวรี `SELECT DISTINCT tenant_id FROM care_job` โดยไม่มี GUC
        #    จะได้ **0 แถวเสมอ** แล้ว worker จะไม่ทำอะไรเลยโดยไม่มี error — เจอจริงตอนเปิด RLS
        #    (ตาราง tenant ของ kernel ไม่มี RLS โดยตั้งใจ เพราะต้องอ่านได้ก่อนจะรู้ว่าเป็น tenant ไหน)
        #
        #    ต้นทุนคือวนทุก tenant แม้ไม่มีงาน — run_due_jobs คืนค่าเร็วถ้าไม่มีงานถึงกำหนด
        tenants = list((await session.execute(select(Tenant.tenant_id))).scalars())
        await session.commit()

        for tenant_id in tenants:
            scope = TenantScope(tenant_id=tenant_id, principal=SYSTEM_PRINCIPAL)
            await bind_tenant(session, tenant_id)
            summary = await svc.run_due_jobs(session, scope)
            for key, value in summary.items():
                totals[key] = totals.get(key, 0) + value
            await session.commit()   # จบงานของ tenant นี้ก่อนเปลี่ยนไป tenant ถัดไป
        await unbind_tenant(session)
    if any(totals.values()):
        logger.info("care_tick: %s", totals)
    return totals
