"""สร้าง role กลางของ platform layer + ผูก permission ตอน install

pstack seed แค่ superuser คนแรก ไม่มี role — ที่นี่จึงสร้าง role ให้พร้อมมอบหมายทีหลัง
(superuser ผ่าน require_permission อยู่แล้ว role นี้ไว้ให้ผู้ดูแลที่ไม่ใช่ superuser)
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ROLE = "platform_admin"
PERMISSIONS = ["platform.tenancy.manage", "platform.consent.manage"]


async def on_install(session: AsyncSession) -> None:
    from addons.users.models import Role

    result = await session.execute(select(Role).where(Role.name == ROLE))
    role = result.scalar_one_or_none()
    if role is None:
        session.add(Role(name=ROLE, permissions=sorted(PERMISSIONS)))
    else:
        role.permissions = sorted(set(role.permissions or []) | set(PERMISSIONS))
    await session.commit()
    logger.info("ap_tenancy: role '%s' พร้อมใช้", ROLE)


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    await on_install(session)
