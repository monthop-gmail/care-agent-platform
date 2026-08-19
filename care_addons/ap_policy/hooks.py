"""โหลด policy ตอน install — ให้ config ที่ผิดหรือหายทำให้ boot ไม่ผ่าน

fail closed ที่ดีต้องล้มตั้งแต่ boot ไม่ใช่ล้มตอนมีงานของผู้ป่วยเข้ามาแล้ว
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_policy.engine import DEFAULT_POLICY_PATH, load_policy
from care_addons.ap_policy.profile import load_profile

logger = logging.getLogger(__name__)


async def on_install(session: AsyncSession) -> None:
    if not DEFAULT_POLICY_PATH.exists():
        raise RuntimeError(
            f"ไม่พบ policy config ที่ {DEFAULT_POLICY_PATH} — "
            "ระบบทำงานโดยไม่มี authority map ไม่ได้ (ADR-0006) "
            "ถ้ารันใน Docker ตรวจว่า Dockerfile copy โฟลเดอร์ policies/ เข้า image แล้ว"
        )
    # โหลด profile ก่อน — `load_policy()` ตรวจว่า authority_map ไม่หลวมกว่าเพดานของ profile
    # ทั้งคู่จึงต้องอ่านได้ตั้งแต่ boot ไม่ใช่ตอนมีงานของผู้ป่วยเข้ามาแล้ว
    profile = load_profile()
    policy = load_policy()
    logger.info(
        "ap_policy: โหลด '%s' แล้ว — %d capability · profile '%s' อนุญาต %d ห้าม %d",
        policy.policy_id,
        len(policy.capabilities),
        profile.profile_id,
        len(profile.allow),
        len(profile.deny),
    )


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    await on_install(session)
