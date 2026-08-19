"""โหลด safety policy ตอน install — เหตุผลเดียวกับ care_escalation/hooks.py

ระบบที่รับสัญญาณความปลอดภัยโดยไม่มีเกณฑ์ว่าจะปลุกคนเมื่อไร อันตรายกว่าไม่มีระบบเลย
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.care_safety.policy import POLICY_PATH, load

logger = logging.getLogger(__name__)


async def on_install(session: AsyncSession) -> None:
    if not POLICY_PATH.exists():
        raise RuntimeError(
            f"ไม่พบ escalation policy ที่ {POLICY_PATH} — care_safety ต้องใช้บล็อก `safety:` ในไฟล์นั้น "
            "ถ้ารันใน Docker ตรวจว่า Dockerfile copy โฟลเดอร์ policies/ เข้า image แล้ว"
        )
    policy = load()
    logger.info(
        "care_safety: เกณฑ์ความมั่นใจ %.2f · หน้าต่างรวมสัญญาณ %d นาที · %d ชนิดที่ตั้งระดับไว้",
        policy.min_confidence,
        policy.dedup_window_minutes,
        len(policy.severity_by_kind),
    )


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    await on_install(session)
