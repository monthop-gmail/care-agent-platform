"""Agent profile — เพดานของสิ่งที่ agent ทำได้ (`agent-platform profile/v1`)

> profile เป็น "เพดาน" ไม่ใช่ "การอนุญาต" — สิทธิ์จริงคือส่วนที่ profile, agent
> และ policy ของ tenant ตกลงตรงกันทั้งสามฝ่าย **ค่าที่กว้างที่สุดชนะไม่ได้**

ก่อนหน้านี้ไฟล์ `profiles/care-agent/profile.yaml` ไม่มีโค้ดไหนอ่านเลย — เป็นเอกสาร
ที่ดูเหมือนกติกาแต่ไม่มีผลบังคับ ซึ่งอันตรายกว่าการไม่มีไฟล์นั้น เพราะคนอ่านแล้วเชื่อว่า
ระบบกันให้อยู่ · ตั้งแต่ไฟล์นี้เป็นต้นไป `ap_policy` โหลดมันจริงทุกครั้งที่ evaluate

🔒 โมดูลนี้ห้ามรู้จักคำของโดเมน (ADR-0003 กฎ 1) — ชื่อ capability เป็นแค่ string
"""

from __future__ import annotations

import fnmatch
from functools import lru_cache
from pathlib import Path

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[2] / "profiles" / "care-agent" / "profile.yaml"

# actor ที่อยู่ใต้เพดานของ profile — คนไม่ได้อยู่ใต้ profile ของ agent
# (ผู้ดูแลที่ยืนยันคำสั่งยาคือการใช้อำนาจของคน ไม่ใช่การที่ agent ทำงาน)
GOVERNED_ACTOR_TYPES = {"agent"}


class ProfileConfigError(RuntimeError):
    """profile ผิดกติกา — ต้องหยุดตั้งแต่ boot ไม่ใช่ปล่อยให้รันแล้วอนุญาตเกิน"""


class AgentProfile:
    def __init__(self, config: dict) -> None:
        self.profile_id: str = config.get("profile_id", "unknown")
        tools = config.get("tools") or {}
        # 🔒 allow ว่าง = ไม่อนุญาต tool ใดเลย ไม่ใช่ "อนุญาตทั้งหมด" (profile/v1)
        self.allow: list[str] = list(tools.get("allow") or [])
        self.deny: list[str] = list(tools.get("deny") or [])
        policy = config.get("policy") or {}
        self.authority_map: dict = policy.get("authority_map") or {}
        self.require_human_for: list[str] = list(policy.get("require_human_for") or [])
        self.deny_capabilities: list[str] = list(policy.get("deny_capabilities") or [])
        if not self.authority_map:
            raise ProfileConfigError(
                f"profile '{self.profile_id}' ไม่มี policy.authority_map — "
                f"profile/v1 บังคับให้มี เพราะมันคือเพดานที่ tenant ลดกว่านี้ไม่ได้"
            )

    def _matches(self, patterns: list[str], capability: str) -> bool:
        return any(fnmatch.fnmatch(capability, pattern) for pattern in patterns)

    def denies(self, capability: str) -> bool:
        """🔒 deny ชนะ allow เสมอ และชนะ authority_map ด้วย"""
        return self._matches(self.deny, capability)

    def allows(self, capability: str) -> bool:
        return self._matches(self.allow, capability)

    def requires_human(self, capability: str) -> bool:
        return self._matches(self.require_human_for, capability)

    def governs(self, actor_type: str | None) -> bool:
        return actor_type in GOVERNED_ACTOR_TYPES

    def ceiling_for(self, risk: str) -> str | None:
        return self.authority_map.get(risk)


@lru_cache(maxsize=4)
def load_profile(path: str | None = None) -> AgentProfile:
    import yaml

    target = Path(path) if path else DEFAULT_PROFILE_PATH
    if not target.exists():
        raise ProfileConfigError(
            f"ไม่พบ agent profile ที่ {target} — ระบบที่ไม่มีเพดานของ agent "
            f"คือระบบที่ policy ของ tenant เผลอเปิดอะไรก็ได้ "
            f"(ถ้ารันใน Docker ตรวจว่า Dockerfile copy โฟลเดอร์ profiles/ เข้า image แล้ว)"
        )
    return AgentProfile(yaml.safe_load(target.read_text(encoding="utf-8")) or {})
