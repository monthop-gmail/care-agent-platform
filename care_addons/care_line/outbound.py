"""ส่ง reminder/แจ้งเตือนออกทาง LINE จริง

ลงทะเบียนกับ care_escalation ตอนโหลดโมดูล — ตั้งแต่นี้ไปข้อความที่ engine สร้าง
จะถูกส่งถึงผู้ป่วย/ผู้ดูแลจริง ไม่ใช่แค่บันทึกลงตาราง
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_tenancy.services import Principal, TenantScope
from care_addons.care_escalation.services import register_sender
from care_addons.care_line import services as line

logger = logging.getLogger(__name__)


async def send_via_line(session: AsyncSession, notification) -> tuple[bool, str | None]:
    """care_escalation เรียกตัวนี้ทุกครั้งที่มีข้อความ channel = line

    ต้องไม่ raise — ช่องทางล่มต้องไม่ทำให้ closed loop ของผู้ป่วยคนอื่นหยุดตาม
    """
    scope = TenantScope(
        tenant_id=notification.tenant_id,
        principal=Principal(type="service", id="care-line"),
    )
    text = notification.text
    if notification.audience == "patient":
        # ผู้ป่วยตอบกลับสั้น ๆ ได้เลย — ลด cognitive load ไม่ต้องเปิดแอป ไม่ต้องกดเมนู
        text = f"{text}\n\n(ตอบว่า “ทำแล้ว” หรือ “ยัง” ได้เลยครับ)"
    return await line.send_text(session, scope, notification.target_principal_id, text)


register_sender("line", send_via_line)
