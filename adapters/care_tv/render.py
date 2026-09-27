"""แปลง presentation intent → แผนการแสดง — ฟังก์ชันบริสุทธิ์ ทดสอบแยกได้

🔒 **ไม่ประเมิน quiet hours หรือ severity ซ้ำ** · intent ที่ได้มาผ่าน
   `effective_presentation()` ของโดเมนแล้ว (ADR-0014 ข้อ 2) — ถ้า adapter ตัดสินใหม่
   ทุกยี่ห้อจะตีความไม่ตรงกัน และไม่มีใครตอบได้ว่าตอนตีสามผู้ป่วยเห็นอะไร
"""

from __future__ import annotations

from dataclasses import dataclass

# วินาทีจริงเป็นการตัดสินใจของอุปกรณ์ · โดเมนบอกแค่ "สั้น" หรือ "จนกว่าจะตอบ"
DWELL_SECONDS = {"short": 8, "medium": 20, "until_answered": None}

# ขนาดตัวอักษรบนจอ 55 นิ้วที่ระยะ 2.5 เมตร — ของอุปกรณ์ล้วน ๆ
SURFACE_LAYOUT = {
    "overlay": {"region": "lower_third", "dim_background": False},
    "full_screen": {"region": "full", "dim_background": True},
    "ambient": {"region": "corner", "dim_background": False},
}


@dataclass(frozen=True)
class RenderPlan:
    region: str
    dim_background: bool
    speak: bool
    seconds: int | None
    needs_answer: bool


def plan(intent: dict | None) -> RenderPlan | None:
    """`None` = ไม่มี intent มา → ไม่แสดงอะไรเป็นพิเศษ (ข้อความไปทางอื่น)"""
    if not intent:
        return None
    layout = SURFACE_LAYOUT[intent["surface"]]
    return RenderPlan(
        region=layout["region"],
        dim_background=layout["dim_background"],
        speak=bool(intent.get("speak")),
        seconds=DWELL_SECONDS[intent["dwell"]],
        needs_answer=intent["response"] == "required",
    )
