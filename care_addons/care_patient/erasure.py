"""สิทธิขอลบข้อมูล — ตัด "สะพานไปหาตัวตน" ไม่ใช่ลบ trail (ADR-0012)

`dec-d1302f96` เคาะทางเลือก A (pseudonymization): audit อ้าง `patient_id` ที่ไม่ผูกตัวตน
โดยตรง · ตัวตนอยู่ในแถวของโดเมนที่ลบได้ · erasure = ลบแถวเหล่านั้น
trail จึงยังตอบได้ว่า **เกิดอะไรขึ้นเมื่อไร** แต่ตอบไม่ได้ว่า **ของใคร**

🔒 ใบนั้นเขียนไว้เองว่า data minimization เป็น *เงื่อนไข* ที่ทำให้ A มีความหมาย ไม่ใช่ของเสริม
   เพราะ A ตัดสะพานเส้นเดียว — ถ้าโดเมนเขียนตัวตนลงอีกหลายที่ การตัดสะพานนั้นไม่เปลี่ยนอะไร
   ADR-0011 กับ ADR-0012 คือการปิดที่เหลือเหล่านั้น และต้องมาก่อนไฟล์นี้

## ทำไมไม่มีทะเบียนตารางให้ลงชื่อ

รูปที่ง่ายกว่าคือให้แต่ละโมดูลมาลงทะเบียนว่าตารางไหนลบได้ · เราไม่ทำแบบนั้น เพราะ
**ทะเบียนที่ต้องมีคนมาเติมคือทะเบียนที่วันหนึ่งจะมีคนลืมเติม** แล้วผลของการลืมคือ
ข้อมูลของคนที่ขอให้ลบ ยังอยู่ในตารางที่ไม่มีใครนึกถึง โดยไม่มีอะไรฟ้อง

ที่นี่จึงอ่านจาก SQLAlchemy registry ตรง ๆ — ตารางไหนมีคอลัมน์ `patient_id` ตารางนั้น
ถูกลบด้วยเสมอ ตารางใหม่ที่ใครเพิ่มพรุ่งนี้เข้าข่ายทันทีโดยไม่ต้องมาแก้ไฟล์นี้

## สิ่งที่ไฟล์นี้ **ไม่** ทำ

* **ไม่แตะ `ap_audit_event`** — append-only ตาม frozen guarantee ของ `event/v1`
* **ไม่เรียก `ap_consent.revoke()`** — `dec-d1302f96` เงื่อนไขข้อ 3 ระบุว่า erasure
  ห้ามเดินทางเดียวกับการถอนความยินยอม เพราะเป็นการกระทำคนละอย่างและมีผลทางกฎหมาย
  คนละแบบ · ถ้า implement ทับกัน บันทึกจะบอกว่าเจ้าของข้อมูลถอนความยินยอม
  ทั้งที่เขาขอให้ลบตัวตน และตรวจย้อนไม่เจอเพราะบันทึกดูปกติ
  ใบยินยอมจึงถูก **ลบ** ที่นี่ ไม่ใช่ถูกเพิกถอน
* **ไม่มี HTTP route** — โดยเจตนา · ขั้นตอนยืนยันของการลบจริงยังไม่มีใครตัดสิน
  และ endpoint ที่ลบข้อมูลผู้ป่วยได้ด้วย request เดียวเป็นของที่ต้องออกแบบก่อน ไม่ใช่แถมมา
"""

from __future__ import annotations

from core.db import Base
from core.tenancy import TenantScope
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action

# ตารางที่ผูกกับผู้ป่วยด้วยชื่อคอลัมน์อื่น — ap_* ห้ามรู้จักคำของโดเมน (ADR-0003)
# ฝั่งโดเมนจึงเป็นคนบอกเองว่าใบยินยอมของใครคือของผู้ป่วยคนนี้
EXTRA_COLUMNS = {"ap_consent_grant": "subject_id"}

# ลบทีหลังสุด — ตารางอื่นมี FK ชี้มาที่นี่
LAST = "care_patient"


class ErasureRefused(PermissionError):
    """การลบข้อมูลของคนต้องมีคนสั่งเสมอ — ไม่มีทางที่ระบบจะลบเอง"""


def erasable_tables() -> list[tuple[str, str]]:
    """(ชื่อตาราง, คอลัมน์ที่ผูกกับผู้ป่วย) — อ่านจาก mapper จริง ไม่ใช่จากทะเบียนที่คนเติม"""
    found: list[tuple[str, str]] = []
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if table is None or table.name == "ap_audit_event":
            continue
        column = EXTRA_COLUMNS.get(table.name)
        if column is None and "patient_id" in table.columns:
            column = "patient_id"
        if column and column in table.columns and "tenant_id" in table.columns:
            found.append((table.name, column))
    # care_patient ไปท้ายสุดเสมอ (FK ondelete=CASCADE ชี้มาที่มัน)
    return sorted(found, key=lambda pair: (pair[0] == LAST, pair[0]))


@care_action("patient.data.erase", autonomous=False)
async def erase_patient(
    session: AsyncSession,
    scope: TenantScope,
    patient_id: str,
    *,
    request_ref: str,
) -> dict:
    """ลบข้อมูลของผู้ป่วยหนึ่งรายตามคำขอใช้สิทธิ์ — `request_ref` คือใบคำขอนอกระบบ

    คืนรายการว่าลบอะไรไปกี่แถว **ให้ผู้ปฏิบัติงานเห็น** · รายละเอียดนั้นไม่ลงไปใน audit
    เพราะ audit เก็บตัวชี้ ไม่ใช่เนื้อหา (ADR-0011) — ใบใน audit บอกแค่ว่าลบไปกี่แถว
    จากกี่ตาราง ซึ่งพอให้ตรวจได้ว่าการลบเกิดขึ้นจริงและเกิดครั้งเดียว
    """
    if scope.principal.type != "human":
        raise ErasureRefused(
            "การลบข้อมูลตามสิทธิ์ของเจ้าของข้อมูลต้องมีคนสั่งเสมอ — "
            f"principal ปัจจุบันเป็น '{scope.principal.type}' (ADR-0012)"
        )
    if not request_ref.strip():
        raise ValueError("ต้องอ้างใบคำขอ — การลบที่ไม่มีที่มาตอบ audit ไม่ได้")
    if any(character.isspace() for character in request_ref):
        # 🔒 เลขใบคำขอ ไม่ใช่คำบรรยาย — audit เก็บตัวชี้ ไม่ใช่เนื้อหา (ADR-0011)
        raise ValueError(f"request_ref ต้องเป็นเลขอ้างอิงใบเดียว ไม่ใช่ข้อความ: {request_ref!r}")

    # 🔒 ยืนยันว่าผู้ป่วยอยู่ใน tenant นี้ก่อน ไม่งั้นคำสั่งลบจะเงียบและไม่มีใครรู้ว่าพลาด
    from care_addons.care_patient.models import CarePatient

    exists = await session.scalar(
        select(CarePatient.patient_id).where(
            CarePatient.tenant_id == scope.tenant_id,
            CarePatient.patient_id == patient_id,
        )
    )
    if exists is None:
        raise LookupError(f"ไม่พบผู้ป่วย {patient_id} ใน tenant นี้")

    deleted: dict[str, int] = {}
    for table_name, column in erasable_tables():
        table = Base.metadata.tables[table_name]
        result = await session.execute(
            delete(table).where(
                table.c.tenant_id == scope.tenant_id,
                table.c[column] == patient_id,
            )
        )
        if result.rowcount:
            deleted[table_name] = result.rowcount

    deleted_orphans = await _delete_orphan_caregivers(session, scope)
    if deleted_orphans:
        deleted["care_caregiver"] = deleted_orphans
    await session.flush()

    # 🔒 ใบนี้ไม่ใช่ CONSENT_REVOKED โดยเจตนา — คนละการกระทำ คนละผลทางกฎหมาย
    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=patient_id,
        care_event_type="care.patient.erased",
        severity="high",
        evidence={"kind": "caregiver_confirmed", "recorded_by": scope.principal.as_dict()},
        transition={"from": "active", "to": "erased", "reason": "ใช้สิทธิ์ขอลบข้อมูล"},
        attributes={
            "record_type": "patient",
            "patient_id": patient_id,
            "subject_ref": request_ref,
            "erased_rows": sum(deleted.values()),
            "erased_tables": len(deleted),
        },
    )
    return {"patient_id": patient_id, "deleted": deleted, "rows": sum(deleted.values())}


async def _delete_orphan_caregivers(session: AsyncSession, scope: TenantScope) -> int:
    """ผู้ดูแลที่ไม่เหลือผู้ป่วยในความดูแลแล้ว — แถวที่ถือชื่อคนไว้โดยไม่มีเหตุให้เก็บต่อ

    ผู้ดูแลที่ยังดูแลผู้ป่วยรายอื่นในบ้านเดียวกันไม่ถูกแตะ — เขาเป็นเจ้าของข้อมูลคนละคน
    และคำขอนี้ไม่ใช่ของเขา
    """
    from care_addons.care_patient.models import CareCaregiver, CareTeamMember

    linked = select(CareTeamMember.caregiver_id).where(CareTeamMember.tenant_id == scope.tenant_id)
    result = await session.execute(
        delete(CareCaregiver)
        .where(
            CareCaregiver.tenant_id == scope.tenant_id,
            CareCaregiver.caregiver_id.not_in(linked),
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def describe_scope() -> dict:
    """ใช้ตอบผู้ตรวจว่าคำสั่งลบครอบอะไรบ้าง — และอะไรที่มันไม่ครอบ"""
    return {
        "tables": [name for name, _ in erasable_tables()],
        "never_erased": ["ap_audit_event"],
        "note": (
            "audit เป็น append-only · หลังลบแล้ว trail ยังตอบได้ว่าเกิดอะไรขึ้นเมื่อไร "
            "แต่ตอบไม่ได้ว่าของใคร เพราะแถวที่แปลง patient_id เป็นคนถูกลบไปแล้ว"
        ),
    }


__all__ = ["ErasureRefused", "describe_scope", "erasable_tables", "erase_patient"]
