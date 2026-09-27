"""การกระทำต่ออุปกรณ์ — โดเมนตัดสินและบันทึก · endpoint เป็นคนลงมือ (ADR-0015)

สามฟังก์ชันในไฟล์นี้เป็น action แรกของระบบที่ **เปลี่ยนสภาพแวดล้อมของผู้ป่วย**
capability อื่นทั้ง 29 ตัวก่อนหน้านี้เป็น notify · record · propose ทั้งหมด

🔒 ที่นี่ไม่มีโค้ดที่คุยกับอุปกรณ์เลยแม้แต่บรรทัดเดียว — และตั้งใจให้เป็นแบบนั้น
   โดเมนตอบว่า *ควรหยุดไหม ใครสั่งได้ และบันทึกว่าอะไรเกิดขึ้น*
   ส่วน *หยุดยังไงบนจอยี่ห้อไหน* เป็นของ adapter (`architecture/care-endpoints.md`)

🔒 ไม่เก็บพฤติกรรมการดูทีวี — `pause` ที่นี่ถูกสั่งจาก **งานที่ถึงกำหนด** หรือจาก **ผู้ดูแล**
   เท่านั้น ไม่ได้ถูกสั่งจากการเฝ้าดูว่าผู้ป่วยดูนานเท่าไร · การเตือนหลังดูนานต้องเก็บ
   ข้อมูลชนิดใหม่ ซึ่งชนข้อจำกัดที่ `platform-contract.yaml` ประกาศไว้ (`task-4c4a109f`)
"""

from __future__ import annotations

from core.tenancy import TenantScope, new_id
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action

# เหตุผลที่สั่ง — code จาก vocabulary ปิด ไม่ใช่ข้อความเสรี (ADR-0011)
TRIGGERS = ["reminder_due", "caregiver_request", "safety_signal"]


class DeviceActionRejected(ValueError):
    """คำสั่งที่ไม่มีที่มาที่ตรวจได้ — audit ต้องตอบได้เสมอว่าทำไมจอถูกหยุด"""


async def _record(
    session: AsyncSession,
    scope: TenantScope,
    patient_id: str,
    *,
    capability: str,
    action: str,
    trigger: str,
) -> dict:
    if trigger not in TRIGGERS:
        raise DeviceActionRejected(
            f"trigger '{trigger}' ไม่อยู่ในชุดปิด {TRIGGERS} — "
            f"การหยุดจอที่ไม่มีที่มาตอบ audit ไม่ได้"
        )
    await audit.emit(
        session,
        scope,
        event_type="EXECUTION_STARTED",
        subject_type="execution",
        subject_id=new_id("exec"),
        care_event_type="care.device.action_requested",
        severity="medium",
        attributes={
            "record_type": "device_action",
            "patient_id": patient_id,
            "capability": capability,
            "kind": action,
            "source_kind": trigger,
        },
    )
    return {"patient_id": patient_id, "action": action, "trigger": trigger}


@care_action("media.playback.pause", autonomous=True)
async def pause_media(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, trigger: str
) -> dict:
    """หยุดสิ่งที่กำลังเล่นอยู่ — **ต้องไม่รอใครอนุมัติ**

    🔒 `critical` + `override_authority: notify` + `requires_full_audit` เพราะความเร็ว
       คือคุณสมบัติด้านความปลอดภัยของมัน · ถ้าการหยุดต้องรออนุมัติ สิ่งที่เกิดตอนต้องหยุด
       จริง ๆ คือมันไม่หยุด (ADR-0029 กฎข้อ 2 ที่ repo นี้เป็นคนเสนอ)
    """
    return await _record(
        session, scope, patient_id,
        capability="media.playback.pause", action="pause", trigger=trigger,
    )


@care_action("media.playback.cancel", autonomous=True)
async def cancel_media(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, trigger: str
) -> dict:
    """ปิดสิ่งที่กำลังเล่นทั้งหมด — อยู่ชั้นเดียวกับ `pause` ตามหลัก `tools.cancel`"""
    return await _record(
        session, scope, patient_id,
        capability="media.playback.cancel", action="cancel", trigger=trigger,
    )


@care_action("media.playback.resume", autonomous=True)
async def resume_media(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, trigger: str
) -> dict:
    """เปิดต่อ — **ต้องไม่ง่ายกว่าการหยุด**

    🔒 `floor.capabilities` บังคับว่าไม่ต่ำกว่า `notify` จึงมีร่องรอยเสมอว่าใครสั่ง
       และไม่เป็น audited exception เพราะไม่มีเหตุผลด้านความเร็วมารองรับ

    🔒 ไม่ประกาศว่า `undoes` `media.playback.pause` — ADR-0029 กฎ 1a: ระหว่างที่จอหยุด
       ผู้ป่วยอาจหลับไปแล้ว การเปิดต่อคือ **การปลุกคน** ไม่ใช่การยกเลิกการหยุด
       สภาพเดิมที่จะคืนไม่มีอยู่แล้ว
    """
    return await _record(
        session, scope, patient_id,
        capability="media.playback.resume", action="resume", trigger=trigger,
    )


__all__ = ["DeviceActionRejected", "cancel_media", "pause_media", "resume_media"]
