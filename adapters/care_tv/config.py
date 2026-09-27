"""config จาก env — ไม่มี credential ใน git และไม่มี PII ใน identity ของอุปกรณ์"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AdapterConfig:
    """ทุกค่ามาจาก env · `device_id` เป็นรหัสอุปกรณ์ ไม่ใช่ข้อมูลของคน

    🔒 ห้ามใส่ `patient_id` หรือชื่อคนลงใน credential ของอุปกรณ์ — อุปกรณ์หนึ่งเครื่อง
       อาจถูกย้ายไปบ้านอื่น และ credential ที่ผูกกับคนจะพาข้อมูลตามไปด้วย
    """

    api_base: str = "http://localhost:8000"
    device_id: str = "tv-unpaired"
    token: str = ""          # จาก env เท่านั้น — ไม่มี default ที่ใช้งานได้
    poll_seconds: float = 5.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AdapterConfig:
        source = os.environ if env is None else env
        return cls(
            api_base=source.get("CARE_TV_API_BASE", cls.api_base),
            device_id=source.get("CARE_TV_DEVICE_ID", cls.device_id),
            token=source.get("CARE_TV_TOKEN", ""),
            poll_seconds=float(source.get("CARE_TV_POLL_SECONDS", cls.poll_seconds)),
        )

    def redacted(self) -> dict:
        """สำหรับ log — token ไม่ออกไปไหนทั้งนั้น"""
        return {
            "api_base": self.api_base,
            "device_id": self.device_id,
            "token": "***" if self.token else "",
            "poll_seconds": self.poll_seconds,
        }
