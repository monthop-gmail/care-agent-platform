"""ของที่บ้าน — กันซื้อซ้ำโดยไม่ห้ามซื้อ

    S10: ซื้ออาหารซ้ำทั้งที่ของยังไม่หมดอายุ → เตือนว่ามีอยู่แล้ว (ไม่ห้ามซื้อ)

🔒 กติกาของ `contracts/inventory/v1` ที่บังคับด้วยโค้ด:
   1. ของที่ไม่รู้วันหมดอายุ — ตอบว่าไม่รู้ ห้ามเดาวันให้
   2. เตือนว่ามีอยู่แล้วได้ **ห้ามห้ามซื้อ** — ไม่มีฟังก์ชันไหนที่คืนค่า "ห้าม"
   3. ของหมดอายุเป็นข้อเท็จจริงจากวันที่ ไม่ใช่การประเมินว่ากินได้/ไม่ได้
   4. ห้ามสรุปว่าผู้ป่วยความจำแย่ลงจากการซื้อซ้ำ — รายงานเป็นจำนวนครั้งเท่านั้น
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action
from care_addons.ap_tenancy.clock import now
from care_addons.ap_tenancy.ids import new_id
from care_addons.ap_tenancy.services import TenantScope, scoped
from care_addons.care_inventory.models import CATEGORIES, CareInventoryItem
from care_addons.care_patient.services import get_patient

DEFAULT_EXPIRY_WARNING_DAYS = 3


def normalize(name: str) -> str:
    return " ".join(name.lower().split())


def is_expired(item: CareInventoryItem, today: date) -> bool:
    """🔒 ข้อเท็จจริงจากวันที่เท่านั้น — ไม่ใช่การประเมินว่ากินได้หรือไม่ได้"""
    return item.expires_on is not None and item.expires_on < today


@care_action("inventory.item.write", autonomous=True)
async def add_item(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    name: str,
    category: str,
    quantity: float = 1.0,
    unit: str = "",
    location: str = "",
    expires_on: date | None = None,
    opened_on: date | None = None,
    note: str | None = None,
) -> CareInventoryItem:
    await get_patient(session, scope, patient_id, required_scope="care.manage")
    if category not in CATEGORIES:
        raise ValueError(f"category ไม่รู้จัก: {category} — ต้องเป็นหนึ่งใน {CATEGORIES}")
    if not name.strip():
        raise ValueError("ชื่อของว่างไม่ได้")

    item = CareInventoryItem(
        item_id=new_id("inv"),
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        name=name.strip(),
        normalized_name=normalize(name),
        category=category,
        quantity=quantity,
        unit=unit,
        location=location,
        expires_on=expires_on,
        opened_on=opened_on,
        status="in_stock",
        recorded_by=scope.principal.as_dict(),
        recorded_at=now(),
        note=note,
    )
    session.add(item)
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=item.item_id,
        care_event_type="care.inventory.changed",
        severity="low",
        transition={"to": "in_stock", "reason": "บันทึกของเข้าบ้าน"},
        attributes={
            "record_type": "inventory_item",
            "patient_id": patient_id,
            "name": item.name,
            "category": category,
            "expires_on": expires_on.isoformat() if expires_on else None,
        },
    )
    return item


async def in_stock(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, name: str | None = None
) -> list[CareInventoryItem]:
    stmt = select(CareInventoryItem).where(
        CareInventoryItem.patient_id == patient_id,
        CareInventoryItem.status == "in_stock",
    )
    if name:
        stmt = stmt.where(CareInventoryItem.normalized_name == normalize(name))
    result = await session.execute(
        scoped(stmt.order_by(CareInventoryItem.expires_on), CareInventoryItem, scope)
    )
    return list(result.scalars())


async def check_before_buying(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, name: str, today: date | None = None
) -> dict:
    """"ซื้ออีกไหม" — 🔒 คำตอบคือ **ข้อมูล** ไม่ใช่ **คำสั่ง**

    ไม่มี key ไหนในผลลัพธ์ที่แปลว่า "ห้ามซื้อ" โดยเจตนา (inventory_rules ข้อ 2)
    ผู้ป่วยที่ถูกห้ามซื้อของกินของตัวเองคือผู้ป่วยที่ถูกพรากศักดิ์ศรีไปทีละนิด
    """
    day = today or now().date()
    existing = await in_stock(session, scope, patient_id, name=name)
    usable = [i for i in existing if not is_expired(i, day)]
    expired = [i for i in existing if is_expired(i, day)]

    result = {
        "name": name,
        "already_at_home": [
            {
                "item_id": i.item_id,
                "name": i.name,
                "quantity": i.quantity,
                "unit": i.unit,
                "location": i.location,
                "expires_on": i.expires_on.isoformat() if i.expires_on else None,
                "expiry_known": i.expires_on is not None,
            }
            for i in usable
        ],
        "expired_at_home": [
            {"item_id": i.item_id, "name": i.name, "expires_on": i.expires_on.isoformat()}
            for i in expired
        ],
        "message": _buying_message(name, usable, expired),
    }
    if usable:
        await audit.emit(
            session,
            scope,
            event_type="STATE_TRANSITION",
            subject_type="record",
            subject_id=usable[0].item_id,
            care_event_type="care.inventory.duplicate_suspected",
            severity="low",
            transition={"to": "in_stock", "reason": "ตรวจก่อนซื้อแล้วพบว่ามีอยู่แล้ว"},
            attributes={
                "record_type": "inventory_item",
                "patient_id": patient_id,
                "name": name,
                "at_home_count": len(usable),
            },
        )
    return result


def _buying_message(name: str, usable: list, expired: list) -> str:
    if not usable and not expired:
        return f"ไม่พบ '{name}' ในบันทึกของที่บ้านครับ (อาจมีอยู่แต่ยังไม่ได้บันทึกไว้)"
    parts = []
    if usable:
        where = usable[0].location or "ที่บ้าน"
        unknown = [i for i in usable if i.expires_on is None]
        detail = f"มี '{name}' อยู่แล้ว {len(usable)} รายการที่{where}"
        if unknown:
            # 🔒 ไม่รู้ = บอกว่าไม่รู้ ไม่ใช่เดาวันให้ (inventory_rules ข้อ 1)
            detail += f" · {len(unknown)} รายการยังไม่ได้บันทึกวันหมดอายุ"
        parts.append(detail)
    if expired:
        parts.append(f"และมี {len(expired)} รายการที่เลยวันหมดอายุแล้ว")
    parts.append("จะซื้อเพิ่มก็ได้นะครับ แค่บอกให้ทราบไว้")
    return " ".join(parts)


async def expiring_soon(
    session: AsyncSession,
    scope: TenantScope,
    patient_id: str,
    *,
    within_days: int = DEFAULT_EXPIRY_WARNING_DAYS,
    today: date | None = None,
) -> dict:
    """ของที่ใกล้หมดอายุและที่เลยไปแล้ว — แยกกันเพราะเป็นคนละเรื่องสำหรับคนที่ต้องตัดสินใจ"""
    day = today or now().date()
    limit = day + timedelta(days=within_days)
    items = await in_stock(session, scope, patient_id)
    return {
        "as_of": day.isoformat(),
        "expired": [
            {"item_id": i.item_id, "name": i.name, "expires_on": i.expires_on.isoformat()}
            for i in items
            if is_expired(i, day)
        ],
        "expiring_soon": [
            {
                "item_id": i.item_id,
                "name": i.name,
                "expires_on": i.expires_on.isoformat(),
                "location": i.location,
            }
            for i in items
            if i.expires_on is not None and day <= i.expires_on <= limit
        ],
        # 🔒 ของที่ไม่รู้วันหมดอายุต้องเห็นได้ ไม่ใช่หายไปเงียบ ๆ ในกอง "ไม่มีปัญหา"
        "expiry_unknown": [
            {"item_id": i.item_id, "name": i.name} for i in items if i.expires_on is None
        ],
    }


@care_action("inventory.item.write", autonomous=True)
async def close_item(
    session: AsyncSession,
    scope: TenantScope,
    item_id: str,
    *,
    status: str,
    reason: str = "",
) -> CareInventoryItem:
    """ใช้หมด/ทิ้ง — ของหายไปจากบ้านต้องมีคนบอก ระบบไม่อนุมานเอง"""
    if status not in ("consumed", "discarded"):
        raise ValueError("status ต้องเป็น consumed หรือ discarded")
    result = await session.execute(
        scoped(
            select(CareInventoryItem).where(CareInventoryItem.item_id == item_id),
            CareInventoryItem,
            scope,
        )
    )
    item = result.scalars().first()
    if item is None:
        raise LookupError(f"ไม่พบของ {item_id}")

    previous = item.status
    item.status = status
    item.closed_at = now()
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=item.item_id,
        care_event_type="care.inventory.changed",
        severity="low",
        evidence={"kind": "caregiver_confirmed", "recorded_by": scope.principal.as_dict()},
        transition={"from": previous, "to": status, "reason": reason or status},
        attributes={
            "record_type": "inventory_item",
            "patient_id": item.patient_id,
            "name": item.name,
        },
    )
    return item


def as_inventory_item(item: CareInventoryItem) -> dict:
    """payload ตาม `contracts/inventory/v1`"""
    payload = {
        "item_id": item.item_id,
        "tenant_id": item.tenant_id,
        "patient_id": item.patient_id,
        "name": item.name,
        "category": item.category,
        "quantity": item.quantity,
        "status": item.status,
        "recorded_by": {k: v for k, v in (item.recorded_by or {}).items() if v},
        "recorded_at": item.recorded_at.isoformat(),
        "expires_on": item.expires_on.isoformat() if item.expires_on else None,
        "opened_on": item.opened_on.isoformat() if item.opened_on else None,
    }
    if item.unit:
        payload["unit"] = item.unit
    if item.location:
        payload["location"] = item.location
    return payload
