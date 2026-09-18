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
* **ไม่มี endpoint ที่ลบได้ด้วย request เดียว** — ADR-0013 ตัดสินว่าการลบต้องใช้ **คนสองคน**
  ทางเข้าของผู้ปฏิบัติงานคือ `request_erasure()` ซึ่งสร้างคำขออนุมัติ ไม่ได้ลบอะไร
  การลบเกิดใน applier ตอนคนที่ **ไม่ใช่ผู้ยื่น** กดอนุมัติ (`ap_approval.decide()` บังคับเอง)
"""

from __future__ import annotations

from typing import Any

from core.db import Base
from core.tenancy import TenantScope
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_approval import services as approvals
from care_addons.ap_approval.models import ApApproval, ApApprovalRequest
from care_addons.ap_audit import services as audit
from care_addons.ap_audit.attributes import problems as attribute_problems
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


def _check_request_ref(request_ref: str) -> None:
    """เลขใบคำขอ ไม่ใช่คำบรรยาย — audit เก็บตัวชี้ ไม่ใช่เนื้อหา (ADR-0011)

    🔒 ตรวจด้วยทะเบียนของ audit เอง ไม่ใช่เขียนกฎซ้ำที่นี่ · ครั้งแรกเราเขียนเองว่า
       "ห้ามมีช่องว่าง" แล้วประโยคภาษาไทยผ่านฉลุย เพราะไทยเขียนติดกัน — แผลเดียวกับ
       ที่เจอตอนปิด `attributes` และเป็นเหตุผลที่กฎต้องอยู่ที่เดียว
    """
    if not request_ref.strip():
        raise ValueError("ต้องอ้างใบคำขอ — การลบที่ไม่มีที่มาตอบ audit ไม่ได้")
    if found := attribute_problems({"subject_ref": request_ref}):
        raise ValueError(f"request_ref ใช้เป็นตัวชี้ใน audit ไม่ได้ — {' · '.join(found)}")


async def _assert_patient_in_tenant(session: AsyncSession, scope: TenantScope, patient_id: str) -> None:
    """🔒 ไม่งั้นคำสั่งลบที่ระบุ id ผิดจะเงียบ และไม่มีใครรู้ว่าพลาด"""
    from care_addons.care_patient.models import CarePatient

    exists = await session.scalar(
        select(CarePatient.patient_id).where(
            CarePatient.tenant_id == scope.tenant_id,
            CarePatient.patient_id == patient_id,
        )
    )
    if exists is None:
        raise LookupError(f"ไม่พบผู้ป่วย {patient_id} ใน tenant นี้")


async def _assert_approved_by_a_second_human(
    session: AsyncSession, scope: TenantScope, patient_id: str, approval_id: str
) -> None:
    """การลบต้องมีใบอนุมัติที่คนอื่น (ไม่ใช่ผู้ยื่น) กดแล้วเท่านั้น — ADR-0013

    🔒 ตรวจที่นี่ ไม่ใช่ที่ route เพราะ route เป็นทางเข้าทางหนึ่ง ส่วนฟังก์ชันนี้คือ
       ทางเดียวที่ข้อมูลหายไปจริง · กฎสองคนต้องอยู่ติดกับการลบ ไม่ใช่ติดกับหน้าจอ
    """
    approval = await session.scalar(
        select(ApApproval).where(
            ApApproval.approval_id == approval_id,
            ApApproval.tenant_id == scope.tenant_id,
        )
    )
    if approval is None:
        raise ErasureRefused(f"ไม่พบใบอนุมัติ {approval_id} ใน tenant นี้ — ลบไม่ได้")
    if approval.decision != "APPROVE":
        raise ErasureRefused(
            f"ใบอนุมัติ {approval_id} เป็น '{approval.decision}' ไม่ใช่ APPROVE — ลบไม่ได้"
        )
    if approval.subject_id != patient_id:
        raise ErasureRefused(
            f"ใบอนุมัติ {approval_id} เป็นของ {approval.subject_id} ไม่ใช่ {patient_id}"
        )
    request = await session.scalar(
        select(ApApprovalRequest).where(
            ApApprovalRequest.request_id == approval.request_id,
            ApApprovalRequest.tenant_id == scope.tenant_id,
        )
    )
    if request is None or request.capability != "patient.data.erase":
        raise ErasureRefused(
            f"ใบอนุมัติ {approval_id} ไม่ได้อนุมัติ capability 'patient.data.erase'"
        )


@care_action("patient.data.erase", autonomous=False)
async def request_erasure(
    session: AsyncSession,
    scope: TenantScope,
    patient_id: str,
    *,
    request_ref: str,
    decision: Any = None,
) -> ApApprovalRequest:
    """ยื่นคำขอลบ — **ไม่ลบอะไรทั้งนั้น** · การลบเกิดตอนคนที่สองอนุมัติ (ADR-0013)

    🔒 ทางนี้เป็นทางเดียวที่ผู้ปฏิบัติงานใช้ · `ap_approval.decide()` บังคับเองว่า
       ผู้ตัดสินต้องเป็นคน และต้องไม่ใช่ผู้ยื่น — กฎสองคนจึงเป็นของโครงสร้าง ไม่ใช่ของกติกา
    """
    if scope.principal.type != "human":
        raise ErasureRefused(
            "การยื่นคำขอลบต้องมีคนยื่นเสมอ — "
            f"principal ปัจจุบันเป็น '{scope.principal.type}' (ADR-0012)"
        )
    _check_request_ref(request_ref)
    await _assert_patient_in_tenant(session, scope, patient_id)

    return await approvals.request_approval(
        session,
        scope,
        decision=decision,
        # ⚠️ `approval/v1` `$.subject.type` เป็นชุดปิดห้าค่า และไม่มีค่าสำหรับ "บันทึกของโดเมน"
        #    — ช่องว่างรูปเดียวกับที่ `event/v1` เคยมีจนเพิ่ม `record` ให้ (agent-platform#14)
        #    เราเลือก `tool_call` เพราะสิ่งที่ถูกอนุมัติคือ *การกระทำ* ไม่ใช่ของที่ผลิตออกมา
        #    บันทึกเป็น gap ในใบ manifest ไม่ได้เงียบ
        subject_type="tool_call",
        subject_id=patient_id,
        summary=f"คำขอใช้สิทธิ์ลบข้อมูล {request_ref}",
        requested_by=scope.principal.as_dict(),
        proposed={"request_ref": request_ref},
    )


async def _apply_approved_erasure(session, scope, request, approval) -> None:
    """applier ของ ap_approval — ทำงานใน transaction เดียวกับคำตัดสิน"""
    await erase_patient(
        session,
        scope,
        request.subject_id,
        request_ref=(request.proposed or {}).get("request_ref", ""),
        approval_id=approval.approval_id,
    )


approvals.register_applier("patient.data.erase", _apply_approved_erasure)


async def erase_patient(
    session: AsyncSession,
    scope: TenantScope,
    patient_id: str,
    *,
    request_ref: str,
    approval_id: str,
) -> dict:
    """ลบข้อมูลของผู้ป่วยหนึ่งรายตามคำขอใช้สิทธิ์ — `request_ref` คือใบคำขอนอกระบบ

    คืนรายการว่าลบอะไรไปกี่แถว **ให้ผู้ปฏิบัติงานเห็น** · รายละเอียดนั้นไม่ลงไปใน audit
    เพราะ audit เก็บตัวชี้ ไม่ใช่เนื้อหา (ADR-0011) — ใบใน audit บอกแค่ว่าลบไปกี่แถว
    จากกี่ตาราง ซึ่งพอให้ตรวจได้ว่าการลบเกิดขึ้นจริงและเกิดครั้งเดียว
    """
    _check_request_ref(request_ref)
    await _assert_patient_in_tenant(session, scope, patient_id)
    await _assert_approved_by_a_second_human(session, scope, patient_id, approval_id)

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


__all__ = [
    "ErasureRefused",
    "describe_scope",
    "erasable_tables",
    "erase_patient",
    "request_erasure",
]
