"""ความสดของคำถามที่ค้างบนจอ — กันการกดปุ่มของเมื่อวานกลายเป็นหลักฐานของวันนี้

🔒 กำหนดตายที่ใช้ตรงนี้ **มาจากโดเมน** (`Envelope.expires_at`) ไม่ได้คิดที่นี่ ·
   adapter มีหน้าที่บังคับตาม ไม่ใช่ตัดสิน (ADR-0016)

🔒 สมุดเล่มนี้อยู่ในหน่วยความจำของ process และตายไปกับการปิดแอป · ของที่ **จำไม่ได้**
   จึงถือว่า "ยังกดได้" ไม่ใช่ "หมดอายุ" — ถ้าตีความกลับกัน ทุกครั้งที่แอปรีสตาร์ต
   การกดยืนยันจริงของผู้ป่วยจะถูกปฏิเสธ ซึ่งแย่กว่าปัญหาที่พยายามแก้
   ด่านจริงที่กันหลักฐานผิดงานยังเป็นฝั่งโดเมน — `acknowledge()` ไม่รับงานที่ปิดแล้ว
"""

from __future__ import annotations

import time
from collections import OrderedDict

MAX_PROMPTS = 64        # จอเดียว คนเดียว · เกินนี้คือไม่ใช่ของจริง


class StalePrompt(RuntimeError):
    """กดตอบคำถามที่หมดอายุไปแล้ว — ต้องไม่กลายเป็น evidence (ADR-0014 ข้อ 5)"""


class PromptBook:
    def __init__(self) -> None:
        self._deadlines: OrderedDict[str, float | None] = OrderedDict()

    def remember(self, care_job_id: str, expires_at: float | None) -> None:
        self._deadlines[care_job_id] = expires_at
        self._deadlines.move_to_end(care_job_id)
        while len(self._deadlines) > MAX_PROMPTS:
            self._deadlines.popitem(last=False)

    def is_fresh(self, care_job_id: str, *, at: float | None = None) -> bool:
        if care_job_id not in self._deadlines:
            return True                     # จำไม่ได้ ≠ หมดอายุ (ดูหัวไฟล์)
        deadline = self._deadlines[care_job_id]
        if deadline is None:
            return True                     # โดเมนประกาศว่าไม่มีกำหนดตาย
        return (at if at is not None else time.time()) <= deadline

    def forget(self, care_job_id: str) -> None:
        self._deadlines.pop(care_job_id, None)

    def __len__(self) -> int:
        return len(self._deadlines)


__all__ = ["MAX_PROMPTS", "PromptBook", "StalePrompt"]
