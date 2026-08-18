"""Background job — เดิน closed loop ทุกนาทีผ่าน ARQ worker

ต่างจาก tick endpoint ตรงที่วนทุก tenant ที่มีงานค้าง
"""

from __future__ import annotations

import logging
from typing import Any

from core.db import get_sessionmaker
from core.jobs import background_job
from sqlalchemy import select

from care_addons.ap_tenancy.services import Principal, TenantScope
from care_addons.care_escalation import services as svc
from care_addons.care_escalation.models import CareJob

logger = logging.getLogger(__name__)

SYSTEM_PRINCIPAL = Principal(type="service", id="care-orchestrator", display_name="Care Orchestrator")


@background_job
async def care_tick(ctx: Any) -> dict:
    totals = {"reminded": 0, "missed": 0, "escalated": 0, "deferred": 0}
    async with get_sessionmaker()() as session:
        tenants = (await session.execute(select(CareJob.tenant_id).distinct())).scalars()
        for tenant_id in list(tenants):
            scope = TenantScope(tenant_id=tenant_id, principal=SYSTEM_PRINCIPAL)
            summary = await svc.run_due_jobs(session, scope)
            for key, value in summary.items():
                totals[key] = totals.get(key, 0) + value
        await session.commit()
    if any(totals.values()):
        logger.info("care_tick: %s", totals)
    return totals
