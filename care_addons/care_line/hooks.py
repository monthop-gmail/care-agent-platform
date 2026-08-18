"""ตรวจว่า LINE channel ที่ใช้กับผู้ป่วยปิด agent bridge ไว้ (ADR-0008)

ถ้าเปิด agent_enabled ไว้ ข้อความของผู้ป่วยจะถูกส่งให้ LLM ตอบ **ควบคู่ไปกับ**
คำตอบ deterministic ของเรา = ผู้ป่วยได้สองคำตอบที่อาจขัดกัน ซึ่งอันตรายกับกลุ่มนี้เป็นพิเศษ
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def on_install(session: AsyncSession) -> None:
    await _warn_if_agent_enabled(session)


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    await _warn_if_agent_enabled(session)


async def _warn_if_agent_enabled(session: AsyncSession) -> None:
    from addons.line_oa.models import LineChannel

    from care_addons.care_line.models import CareLineBinding

    bound_channels = set(
        (await session.execute(select(CareLineBinding.channel_id))).scalars()
    )
    if not bound_channels:
        return
    result = await session.execute(
        select(LineChannel).where(
            LineChannel.channel_id.in_(bound_channels), LineChannel.agent_enabled.is_(True)
        )
    )
    for channel in result.scalars():
        logger.warning(
            "LINE channel '%s' ใช้กับผู้ป่วยอยู่แต่ยังเปิด agent_enabled — "
            "ผู้ป่วยจะได้คำตอบซ้อนกันสองชุด ควรตั้งเป็น false (ADR-0008)",
            channel.channel_id,
        )
