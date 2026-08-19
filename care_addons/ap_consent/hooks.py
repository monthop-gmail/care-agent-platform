"""ผูก permission ของ consent เข้ากับ role กลางของ platform layer"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ROLE = "platform_admin"
PERMISSIONS = ["platform.consent.manage"]


async def on_install(session: AsyncSession) -> None:
    from addons.users.models import Role

    result = await session.execute(select(Role).where(Role.name == ROLE))
    role = result.scalar_one_or_none()
    if role is None:
        session.add(Role(name=ROLE, permissions=sorted(PERMISSIONS)))
    else:
        role.permissions = sorted(set(role.permissions or []) | set(PERMISSIONS))
    await session.commit()
    logger.info("ap_consent: permission พร้อมใช้บน role '%s'", ROLE)


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    await on_install(session)
