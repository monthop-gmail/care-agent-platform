"""ทำให้ **ไม่ต้องจำ** ดีกว่าช่วยจำ

blueprint พูดไว้ตรง ๆ: อย่าพยายามทำให้ AI จำแทนทุกอย่าง ให้ AI ช่วยออกแบบ
environment ที่ไม่ต้องจำ — ใช้แล้วลงตะกร้า · ยังไม่ใช้อยู่ในตู้ · ของประจำตัวอยู่ที่เดิมเสมอ

🔒 กติกาของ `contracts/home/v1` ที่บังคับด้วยโค้ด:
   1. AI ห้ามเดาสถานะจากภาพหรือพฤติกรรม — เปลี่ยนสถานะได้จากการยืนยันของคนเท่านั้น
   2. ไม่แน่ใจ = `unknown` แล้วเสนอ workflow ที่ปลอดภัย ห้ามบอกว่า "สะอาด"
   3. ตอบ "ของอยู่ไหน" จากบันทึกล่าสุดเท่านั้น ไม่มีบันทึก = บอกว่าไม่มีข้อมูล
   4. ห้ามใช้จำนวนของที่หายเป็นตัวชี้วัดอาการของผู้ป่วย
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action
from care_addons.ap_tenancy.clock import now
from care_addons.ap_tenancy.ids import new_id
from care_addons.ap_tenancy.services import TenantScope, scoped
from care_addons.care_home.models import ITEM_KINDS, ITEM_STATES, CareHomeItem
from care_addons.care_patient.services import get_patient

# 🔒 principal ที่ยืนยันสถานะได้ — เครื่องจักรอยู่ในนี้ไม่ได้ (home_rules ข้อ 1)
CONFIRMING_PRINCIPAL_TYPES = {"human"}

# workflow ที่ปลอดภัยเมื่อ "จำไม่ได้" — เลือกทางที่ผิดแล้วเสียหายน้อยที่สุด
# ใส่ผ้าที่สะอาดลงตะกร้าซัก = เสียค่าซักรอบหนึ่ง · ใส่ผ้าที่ใช้แล้วออกไปข้างนอก = ศักดิ์ศรี
SAFE_FALLBACK = {
    "clothing": ("in_laundry", "ถ้าจำไม่ได้ว่าใส่แล้วหรือยัง ใส่ตะกร้าผ้าที่ใช้แล้วไว้ก่อนนะครับ"),
}


class HomeRuleViolation(PermissionError):
    """กติกาของของใช้ประจำตัว — ไม่ใช่ error ธรรมดา"""


@care_action("home.item.write", autonomous=True)
async def add_item(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    kind: str,
    label: str,
    home_location: str = "",
    state: str = "unknown",
) -> CareHomeItem:
    await get_patient(session, scope, patient_id, required_scope="care.manage")
    if kind not in ITEM_KINDS:
        raise ValueError(f"kind ไม่รู้จัก: {kind} — ต้องเป็นหนึ่งใน {ITEM_KINDS}")
    if state not in ITEM_STATES:
        raise ValueError(f"state ไม่รู้จัก: {state}")
    if not label.strip():
        raise ValueError("label ว่างไม่ได้ — ผู้ป่วยต้องอ่านแล้วรู้ว่าของชิ้นไหน")

    item = CareHomeItem(
        item_id=new_id("hom"),
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        kind=kind,
        label=label.strip(),
        state=state,
        home_location=home_location,
        created_at=now(),
    )
    session.add(item)
    await session.flush()
    await _emit(session, scope, item, previous=None, reason="บันทึกของประจำตัว")
    return item


async def get_item(session: AsyncSession, scope: TenantScope, item_id: str) -> CareHomeItem:
    result = await session.execute(
        scoped(select(CareHomeItem).where(CareHomeItem.item_id == item_id), CareHomeItem, scope)
    )
    item = result.scalars().first()
    if item is None:
        raise LookupError(f"ไม่พบของ {item_id}")
    return item


@care_action("home.item.write", autonomous=True)
async def set_state(
    session: AsyncSession,
    scope: TenantScope,
    item_id: str,
    *,
    state: str,
    confirmed_by,
    location: str | None = None,
) -> CareHomeItem:
    """เปลี่ยนสถานะ — 🔒 ต้องมีคนยืนยันเสมอ (home_rules ข้อ 1)

    ระบบไม่มีทางรู้เองว่าเสื้อตัวไหนใส่แล้ว การเดาแล้วผิดทำให้ผู้ป่วยใส่ผ้าที่ใช้แล้ว
    ออกไปข้างนอก ซึ่งเป็นความเสียหายที่ระบบไม่ควรเสี่ยงเพื่อความสะดวกเล็กน้อย
    """
    if state not in ITEM_STATES:
        raise ValueError(f"state ไม่รู้จัก: {state}")
    if getattr(confirmed_by, "type", None) not in CONFIRMING_PRINCIPAL_TYPES:
        raise HomeRuleViolation(
            f"สถานะของใช้เปลี่ยนได้จากการยืนยันของคนเท่านั้น — "
            f"ได้รับ principal type '{getattr(confirmed_by, 'type', None)}' (contracts/home/v1)"
        )

    item = await get_item(session, scope, item_id)
    previous = item.state
    item.state = state
    item.last_seen_at = now()
    item.last_confirmed_by = confirmed_by.as_dict()
    if location is not None:
        item.home_location = location
    await session.flush()
    await _emit(session, scope, item, previous=previous, reason="ยืนยันสถานะโดยคน")
    return item


def safe_workflow_for(item: CareHomeItem) -> dict:
    """"จำไม่ได้" → ทางที่ปลอดภัย — 🔒 ไม่ใช่การเดาว่าของสะอาดหรือไม่ (home_rules ข้อ 2)"""
    state, message = SAFE_FALLBACK.get(
        item.kind, ("unknown", f"ยังไม่แน่ใจเรื่อง '{item.label}' — บันทึกไว้ว่ายังไม่ทราบสถานะครับ")
    )
    return {"item_id": item.item_id, "suggested_state": state, "message": message}


@care_action("home.item.write", autonomous=True)
async def mark_unsure(
    session: AsyncSession, scope: TenantScope, item_id: str
) -> dict:
    """ผู้ป่วยตอบว่า "จำไม่ได้" — บันทึกความไม่รู้ตามจริง แล้วเสนอทางที่ปลอดภัย

    🔒 ระบบ **ไม่** เปลี่ยนสถานะให้เอง — มันแค่เสนอ คนยังเป็นคนตัดสิน
    """
    item = await get_item(session, scope, item_id)
    previous = item.state
    item.state = "unknown"
    item.last_seen_at = now()
    await session.flush()
    await _emit(session, scope, item, previous=previous, reason="ผู้ป่วยตอบว่าจำไม่ได้")
    return safe_workflow_for(item)


async def where_is(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, label: str
) -> dict:
    """"กุญแจอยู่ไหน" — 🔒 ตอบจากบันทึกเท่านั้น ไม่มีบันทึก = บอกว่าไม่มีข้อมูล (ADR-0004)"""
    needle = " ".join(label.lower().split())
    result = await session.execute(
        scoped(
            select(CareHomeItem).where(CareHomeItem.patient_id == patient_id),
            CareHomeItem,
            scope,
        )
    )
    matches = [i for i in result.scalars() if needle in i.label.lower()]
    if not matches:
        return {
            "found": False,
            "message": f"ยังไม่มีบันทึกเรื่อง '{label}' ครับ — ผมไม่ทราบว่าอยู่ไหน",
        }
    item = matches[0]
    if not item.home_location:
        return {
            "found": True,
            "item_id": item.item_id,
            "label": item.label,
            "message": f"มีบันทึก '{item.label}' ไว้ แต่ยังไม่ได้ระบุที่เก็บประจำครับ",
        }
    seen = item.last_seen_at.isoformat() if item.last_seen_at else None
    return {
        "found": True,
        "item_id": item.item_id,
        "label": item.label,
        "home_location": item.home_location,
        "state": item.state,
        "last_seen_at": seen,
        "message": f"'{item.label}' เก็บไว้ที่{item.home_location}ครับ",
    }


@care_action("home.item.write", autonomous=True)
async def set_aside(
    session: AsyncSession,
    scope: TenantScope,
    item_ids: list[str],
    *,
    for_date: date,
    reason: str,
) -> list[CareHomeItem]:
    """เตรียมของไว้ล่วงหน้าสำหรับวันพรุ่งนี้ (เช่น ชุดสำหรับวันนัดหมอ)

    ตอนกลางคืนเตรียมไว้ · ตอนเช้าบอกว่า "ชุดที่เตรียมไว้อยู่ตรงนี้" — ผู้ป่วยไม่ต้องเลือกเอง
    ในเวลาที่ยังไม่ตื่นเต็มที่ ซึ่งเป็นเวลาที่ตัดสินใจยากที่สุดของวัน
    """
    items = []
    for item_id in item_ids:
        item = await get_item(session, scope, item_id)
        item.set_aside_for = for_date
        item.set_aside_reason = reason
        items.append(item)
    await session.flush()
    for item in items:
        await _emit(session, scope, item, previous=item.state, reason=f"เตรียมไว้สำหรับ {for_date}")
    return items


async def prepared_for(
    session: AsyncSession, scope: TenantScope, patient_id: str, day: date
) -> list[CareHomeItem]:
    result = await session.execute(
        scoped(
            select(CareHomeItem).where(
                CareHomeItem.patient_id == patient_id, CareHomeItem.set_aside_for == day
            ),
            CareHomeItem,
            scope,
        )
    )
    return list(result.scalars())


async def _emit(
    session: AsyncSession,
    scope: TenantScope,
    item: CareHomeItem,
    *,
    previous: str | None,
    reason: str,
) -> None:
    transition = {"to": item.state, "reason": reason}
    if previous is not None:
        transition["from"] = previous
    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=item.item_id,
        care_event_type="care.home.item_updated",
        severity="low",
        evidence=(
            {"kind": "caregiver_confirmed", "recorded_by": item.last_confirmed_by}
            if item.last_confirmed_by
            else None
        ),
        transition=transition,
        attributes={
            "record_type": "home_item",
            "patient_id": item.patient_id,
            "kind": item.kind,
            "label": item.label,
        },
    )


def as_home_item(item: CareHomeItem) -> dict:
    """payload ตาม `contracts/home/v1`"""
    payload = {
        "item_id": item.item_id,
        "tenant_id": item.tenant_id,
        "patient_id": item.patient_id,
        "kind": item.kind,
        "label": item.label,
        "state": item.state,
        "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
        "set_aside_for": item.set_aside_for.isoformat() if item.set_aside_for else None,
    }
    if item.home_location:
        payload["home_location"] = item.home_location
    if item.last_confirmed_by:
        payload["last_confirmed_by"] = {k: v for k, v in item.last_confirmed_by.items() if v}
    return payload
