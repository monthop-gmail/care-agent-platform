"""จับคู่อุปกรณ์ — ใช้รูปที่ `care_line` พิสูจน์แล้ว ไม่คิดใหม่

🔒 **ห้ามบันทึกตัวโค้ดจับคู่ลง audit หรือ log** — ใครอ่าน log ได้จะผูกอุปกรณ์แทนได้ทันที
   คำกำกับนี้อยู่ใน `care_line/services.py` แล้วสำหรับ LINE · ที่นี่ถือกติกาเดียวกัน

🔒 credential ของอุปกรณ์ **ไม่มี PII** — อุปกรณ์หนึ่งเครื่องอาจถูกย้ายไปบ้านอื่น
   credential ที่ผูกกับคนจะพาข้อมูลตามไปด้วย
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceCredential:
    """สิ่งที่อุปกรณ์เก็บไว้หลังจับคู่เสร็จ"""

    device_id: str
    token: str

    def fingerprint(self) -> str:
        """ใช้ใน log แทนตัว token — ยืนยันว่าเป็นเครื่องเดิมได้โดยไม่เปิด token"""
        return hashlib.sha256(self.token.encode()).hexdigest()[:12]

    def for_log(self) -> dict:
        return {"device_id": self.device_id, "token_fingerprint": self.fingerprint()}


def redact_pairing_code(message: str, code: str) -> str:
    """ใช้ก่อน log ทุกครั้งที่ข้อความอาจมีโค้ดอยู่

    มีไว้เพราะกฎ "ห้าม log โค้ด" ที่ไม่มีเครื่องมือช่วย คือกฎที่วันหนึ่งจะมีคนลืม
    """
    return message.replace(code, "***") if code else message
