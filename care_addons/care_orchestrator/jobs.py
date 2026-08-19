"""รอบวัน — ส่งสรุปตอนที่ถึงเวลาของผู้ป่วยแต่ละคน

แยกจาก `care_tick` (ทุกนาที) โดยตั้งใจ: งานรอบวันไม่ต้องละเอียดระดับนาที
แต่ต้องรันถี่พอที่ผู้ป่วยใน timezone ที่มี offset ครึ่งชั่วโมงจะไม่ได้สรุปช้าไปครึ่งวัน
"""

from __future__ import annotations

import logging
from typing import Any

from addons.tenancy.models import Tenant
from core.db import get_sessionmaker
from core.jobs import periodic_job
from core.tenancy import Principal, TenantScope, bind_tenant, unbind_tenant
from sqlalchemy import select

from care_addons.care_orchestrator import services as svc

logger = logging.getLogger(__name__)

SYSTEM_PRINCIPAL = Principal(type="service", id="care-orchestrator", display_name="Care Orchestrator")


@periodic_job(minute={0, 15, 30, 45})
async def care_daily_tick(ctx: Any) -> dict:
    """🔒 หนึ่ง tenant = หนึ่ง transaction เหมือน care_tick (RLS GUC มีอายุแค่ใน transaction)

    งานของรอบนี้: สร้างงานประจำวัน → ส่งสรุปที่ถึงเวลา → ปิดคำขออนุมัติที่เลยกำหนด
    """
    totals = {
        "routine_jobs": 0,
        "careplan_jobs": 0,
        "skipped_no_consent": 0,
        "stalled_steps": 0,
        "summaries": 0,
        "expired_approvals": 0,
    }
    async with get_sessionmaker()() as session:
        # หารายชื่อ tenant จาก control plane ของ kernel — ตารางโดเมนเปิด RLS อยู่
        tenants = list((await session.execute(select(Tenant.tenant_id))).scalars())
        await session.commit()

        for tenant_id in tenants:
            scope = TenantScope(tenant_id=tenant_id, principal=SYSTEM_PRINCIPAL)
            await bind_tenant(session, tenant_id)
            summary = await svc.run_cycle(session, scope)
            for key, value in summary.items():
                totals[key] = totals.get(key, 0) + value
            await session.commit()
        await unbind_tenant(session)
    if any(totals.values()):
        logger.info("care_daily_tick: %s", totals)
    return totals
