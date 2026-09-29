"""ผู้ผลิตสรุปประจำวัน — ตัวที่ **ส่งจริง** ไม่ใช่ตัวที่ตอบเมื่อถูกถาม

ADR-0016 ประกาศกฎกำหนดตายของ `orientation` ไว้แล้ว แต่เขียนกำกับไว้ตรง ๆ ว่า
**ยังไม่มีผู้ผลิต** — สรุปประจำวันอ่านผ่าน API เท่านั้น ใบนี้ปิดช่องนั้น

🔒 สรุปประจำวันไม่ใช่งานที่ต้องตอบ — ไม่มี `CareJob` ไม่มีปุ่มให้กด และ
   **ไม่มีทางกลายเป็นหลักฐานว่าใครทำอะไร** (ADR-0014 ข้อ 5) · มันคือการบอกว่าวันนี้วันอะไร

🔒 ใบของวันเดียวกันแทนกันได้ ใบข้ามวันแทนกันไม่ได้ — สายงานจึงมีวันที่อยู่ในชื่อ
   ถ้าไม่มีวันที่ สรุปของเมื่อวานจะถูกนับเป็นใบเดียวกับของวันนี้
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from core.clock import now
from core.tenancy import TenantScope, scoped
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_policy.services import care_action
from care_addons.care_endpoint import expiry
from care_addons.care_escalation import services as jobs
from care_addons.care_escalation.models import CareNotification
from care_addons.care_orientation.services import daily_brief
from care_addons.care_patient.services import get_patient

# คำขอของสรุปประจำวัน — เป็น **คำขอ** เท่านั้น `effective_presentation()` เป็นผู้ตัดสิน
# (ADR-0014 ข้อ 2) · ตอนกลางคืนจะถูกลดเป็น ambient และไม่มีเสียงโดยที่ที่นี่ไม่ต้องรู้
REQUESTED_PRESENTATION = {
    "surface": "overlay",
    "speak": True,
    "response": "none",      # 🔒 ไม่มีปุ่มให้ตอบ — ไม่มีอะไรให้กลายเป็นหลักฐาน
    "dwell": "medium",
}


def stream_for(patient_id: str, local_day: date) -> str:
    """สายงานของสรุปประจำวัน — หนึ่งสายต่อหนึ่งวันของผู้ป่วยหนึ่งคน"""
    return f"orientation:{patient_id}:{local_day.isoformat()}"


async def _latest_in_stream(
    session: AsyncSession, scope: TenantScope, stream: str
) -> CareNotification | None:
    return await session.scalar(
        scoped(
            select(CareNotification)
            .where(CareNotification.stream == stream)
            .order_by(CareNotification.id.desc())
            .limit(1),
            CareNotification,
            scope,
        )
    )


@care_action("orientation.brief.send")
async def publish_daily_brief(
    session: AsyncSession, scope: TenantScope, patient_id: str
) -> CareNotification | None:
    """ส่งสรุปของวันนี้ออกช่องทางของผู้ป่วย — เรียกซ้ำได้ ไม่ส่งซ้ำ

    คืน `None` เมื่อ **ไม่มีอะไรใหม่ต้องส่ง** ซึ่งต่างจากการส่งไม่สำเร็จ
    (ส่งไม่สำเร็จจะเห็นที่ `delivery_status` ของแถวที่คืนมา)
    """
    patient = await get_patient(session, scope, patient_id, required_scope="care.read")
    local_day = now().astimezone(ZoneInfo(patient.timezone)).date()
    stream = stream_for(patient_id, local_day)

    brief = await daily_brief(session, scope, patient_id)
    text = brief["text"]

    previous = await _latest_in_stream(session, scope, stream)
    if previous is not None and previous.text == text:
        # 🔒 ข้อความเดิมของวันเดิม = ไม่มีอะไรใหม่ · ส่งซ้ำคือรบกวนโดยไม่มีข้อมูลเพิ่ม
        return None

    notification = CareNotification(
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        audience="patient",
        target_principal_id=patient_id,
        channel=(patient.channels or ["app"])[0],
        text=text,
        severity="low",
        presentation=jobs.effective_presentation(
            patient, requested=REQUESTED_PRESENTATION, severity="low", when=now()
        ),
        correlation_id=scope.correlation_id,
        sent_at=now(),
        stream=stream,
    )
    session.add(notification)
    # กำหนดตายก่อนของออกจากโดเมนเสมอ (ADR-0016) — ที่นี่คือสิ้นวันของผู้ป่วยเอง
    notification.expires_at, notification.expiry_class = await expiry.for_notification(
        session, scope, notification, patient=patient
    )
    await session.flush()
    await jobs.deliver(session, scope, notification)
    return notification


__all__ = ["REQUESTED_PRESENTATION", "publish_daily_brief", "stream_for"]
