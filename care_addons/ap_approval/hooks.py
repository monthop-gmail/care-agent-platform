"""ผูก permission ของ approval เข้ากับ role กลางของ platform layer

🔒 `platform.approval.decide` แยกจาก `.read` โดยตั้งใจ — คนที่เห็นคิวรออนุมัติ
   ไม่จำเป็นต้องเป็นคนที่กดอนุมัติได้
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ROLE = "platform_admin"
PERMISSIONS = ["platform.approval.read", "platform.approval.decide"]


async def on_install(session: AsyncSession) -> None:
    from addons.users.models import Role

    result = await session.execute(select(Role).where(Role.name == ROLE))
    role = result.scalar_one_or_none()
    if role is None:
        session.add(Role(name=ROLE, permissions=sorted(PERMISSIONS)))
    else:
        role.permissions = sorted(set(role.permissions or []) | set(PERMISSIONS))
    await session.commit()
    logger.info("ap_approval: permission พร้อมใช้บน role '%s'", ROLE)


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    await on_install(session)
