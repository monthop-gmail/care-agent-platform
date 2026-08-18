"""โหลด escalation policy ตอน install — เหตุผลเดียวกับ ap_policy/hooks.py"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.care_escalation.policy import POLICY_PATH, load

logger = logging.getLogger(__name__)


async def on_install(session: AsyncSession) -> None:
    if not POLICY_PATH.exists():
        raise RuntimeError(
            f"ไม่พบ escalation policy ที่ {POLICY_PATH} — "
            "closed loop ทำงานโดยไม่มีกติกาการเตือนซ้ำ/ส่งต่อไม่ได้ "
            "ถ้ารันใน Docker ตรวจว่า Dockerfile copy โฟลเดอร์ policies/ เข้า image แล้ว"
        )
    policy = load()
    logger.info(
        "care_escalation: โหลด '%s' — max_attempts=%d backoff=%s",
        policy.policy_id,
        policy.max_attempts,
        policy.backoff_minutes,
    )


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    await on_install(session)
