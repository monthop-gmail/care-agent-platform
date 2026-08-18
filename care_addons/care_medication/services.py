"""Medication memory

สิ่งที่โมดูลนี้ตอบได้:
    "ตอนนี้ต้องกินยังไง"   → active version เท่านั้น
    "เมื่อก่อนกินยังไง"     → ทั้ง chain
    "ใครสั่ง เปลี่ยนเมื่อไร" → prescribed_by + effective_from ของแต่ละ version

🔒 AI สร้างได้แค่ proposed — การทำให้ active ต้องมีคน (ADR-0006)
🔒 ยาชนกันไม่ใช่หน้าที่ agent ตัดสิน — detect แล้วหยุด ไม่เลือกข้าง (ADR-0005 ข้อ 4)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action
from care_addons.ap_tenancy.clock import now
from care_addons.ap_tenancy.ids import new_id
from care_addons.ap_tenancy.services import Principal, TenantScope, scoped
from care_addons.care_medication.models import (
    INSTRUCTION_SOURCES,
    RELATION_TO_MEAL,
    CareMedicationVersion,
)
from care_addons.care_patient.services import feature_enabled, get_patient

ACTIVE_STATUSES = ("active", "needs_reconciliation")


class MedicationRuleViolation(PermissionError):
    """กติกาของโดเมนยา — ไม่ใช่ error ธรรมดา ต้องอ่านข้อความให้ครบก่อนแก้"""


def normalize(name: str) -> str:
    return " ".join(name.lower().split())


def _validate_schedule(schedule: list[dict]) -> list[dict]:
    if not schedule:
        raise ValueError("medication ต้องมี schedule อย่างน้อยหนึ่งรายการ")
    cleaned = []
    for entry in schedule:
        relation = entry.get("relation_to_meal")
        if relation not in RELATION_TO_MEAL:
            # 🔒 ห้ามเดา — ค่าที่ไม่รู้จักต้องถูกปฏิเสธที่ intake (ADR-0005 ข้อ 2)
            raise ValueError(
                f"relation_to_meal ไม่รู้จัก: {relation!r} — ต้องเป็นหนึ่งใน {RELATION_TO_MEAL}"
            )
        cleaned.append(
            {
                "time": entry.get("time", ""),
                "relation_to_meal": relation,
                "dose": entry.get("dose", ""),
            }
        )
    return cleaned


@care_action("medication.regimen.propose", autonomous=True)
async def propose_version(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    name: str,
    schedule: list[dict],
    instruction_source: str,
    medication_id: str | None = None,
    route: str = "oral",
    prescribed_by: dict | None = None,
    reason: str | None = None,
    effective_from: datetime | None = None,
) -> CareMedicationVersion:
    """เสนอคำสั่งใช้ยา — ได้แค่ `proposed` เท่านั้น ต่อให้ผู้เรียกเป็นคน

    ที่แยก propose ออกจาก confirm เพราะ agent ถอดความจากหมอได้ แต่ยืนยันแทนคนไม่ได้
    """
    patient = await get_patient(session, scope, patient_id, required_scope="care.manage")
    if not feature_enabled(patient, "medication"):
        raise MedicationRuleViolation("care_profile.medication ยังปิดอยู่สำหรับผู้ป่วยรายนี้")
    if instruction_source not in INSTRUCTION_SOURCES:
        raise ValueError(f"instruction_source ไม่รู้จัก: {instruction_source}")

    version = CareMedicationVersion(
        version_id=new_id("mv"),
        medication_id=medication_id or new_id("med"),
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        name=name,
        normalized_name=normalize(name),
        route=route,
        schedule=_validate_schedule(schedule),
        status="proposed",
        instruction_source=instruction_source,
        prescribed_by=prescribed_by,
        effective_from=effective_from or now(),
        reason=reason,
    )
    session.add(version)
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="artifact",
        subject_id=version.version_id,
        care_event_type="care.medication.changed",
        transition={"from": None, "to": "proposed", "reason": reason or "proposed"},
        attributes={
            "record_type": "medication_version",
            "patient_id": patient_id,
            "medication_id": version.medication_id,
            "name": name,
            "instruction_source": instruction_source,
        },
    )
    return version


@care_action("medication.regimen.write", autonomous=False)
async def confirm_version(
    session: AsyncSession,
    scope: TenantScope,
    version_id: str,
    *,
    confirmed_by: Principal,
    decision=None,
) -> CareMedicationVersion:
    """ทำให้ proposal เป็นคำสั่งจริง — **คนเท่านั้นที่ทำได้**

    policy บอกว่า capability นี้เป็น human_command_required เสมอ (มีเพดานใน floor)
    ที่นี่จึงบังคับซ้ำอีกชั้นว่า principal ที่ยืนยันต้องเป็น human จริง ๆ
    """
    if confirmed_by.type != "human":
        raise MedicationRuleViolation(
            f"ผู้ยืนยันต้องเป็นคน — ได้รับ principal type '{confirmed_by.type}' "
            f"(ADR-0006: medication ทุก action เป็น human_command_required)"
        )
    if decision is not None and decision.authority != "human_command_required":
        raise MedicationRuleViolation(
            f"policy ของ tenant ให้ authority '{decision.authority}' กับการแก้ยา "
            f"ซึ่งต่ำกว่าเพดานที่ ADR-0006 กำหนด — แก้ policies/care-authority-map.yaml"
        )

    version = await session.get(CareMedicationVersion, version_id)
    if version is None or version.tenant_id != scope.tenant_id:
        raise LookupError(f"ไม่พบ medication version {version_id}")
    if version.status != "proposed":
        raise MedicationRuleViolation(
            f"ยืนยันได้เฉพาะ version ที่ยัง proposed — ตอนนี้เป็น '{version.status}'"
        )

    # ปิดสมุดของเวอร์ชันก่อนหน้า — ไม่ใช่การแก้ของเก่า
    previous = await _active_versions(session, scope, version.patient_id, version.medication_id)
    for old in previous:
        old.status = "superseded"
        old.superseded_by = version.version_id

    version.status = "active"
    version.confirmed_by = confirmed_by.as_dict()
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="artifact",
        subject_id=version.version_id,
        care_event_type="care.medication.changed",
        policy_result=decision.as_policy_result() if decision else None,
        evidence={"kind": "caregiver_confirmed", "recorded_by": confirmed_by.as_dict()},
        transition={"from": "proposed", "to": "active", "reason": version.reason or "confirmed"},
        attributes={
            "record_type": "medication_version",
            "patient_id": version.patient_id,
            "medication_id": version.medication_id,
            "superseded": [v.version_id for v in previous],
        },
    )
    await detect_conflicts(session, scope, version.patient_id)
    return version


@care_action("medication.regimen.stop", autonomous=False)
async def stop_medication(
    session: AsyncSession,
    scope: TenantScope,
    medication_id: str,
    *,
    patient_id: str,
    stopped_by: Principal,
    reason: str,
    decision=None,
) -> CareMedicationVersion:
    """หยุดยา — สร้างเวอร์ชันใหม่ที่ status=stopped ไม่ใช่ลบของเก่า"""
    if stopped_by.type != "human":
        raise MedicationRuleViolation("การหยุดยาต้องมาจากคนเท่านั้น (ADR-0006)")

    current = await _active_versions(session, scope, patient_id, medication_id)
    if not current:
        raise LookupError(f"ไม่มี active version ของ {medication_id}")
    latest = current[0]

    version = CareMedicationVersion(
        version_id=new_id("mv"),
        medication_id=medication_id,
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        name=latest.name,
        normalized_name=latest.normalized_name,
        route=latest.route,
        schedule=[],
        status="stopped",
        instruction_source=latest.instruction_source,
        prescribed_by=latest.prescribed_by,
        effective_from=now(),
        reason=reason,
        confirmed_by=stopped_by.as_dict(),
    )
    session.add(version)
    for old in current:
        old.status = "superseded"
        old.superseded_by = version.version_id
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="artifact",
        subject_id=version.version_id,
        care_event_type="care.medication.changed",
        policy_result=decision.as_policy_result() if decision else None,
        evidence={"kind": "caregiver_confirmed", "recorded_by": stopped_by.as_dict()},
        transition={"from": "active", "to": "stopped", "reason": reason},
        attributes={
            "record_type": "medication_version",
            "patient_id": patient_id,
            "medication_id": medication_id,
        },
    )
    return version


async def _active_versions(
    session: AsyncSession, scope: TenantScope, patient_id: str, medication_id: str | None = None
) -> list[CareMedicationVersion]:
    stmt = select(CareMedicationVersion).where(
        CareMedicationVersion.patient_id == patient_id,
        CareMedicationVersion.status.in_(ACTIVE_STATUSES),
    )
    if medication_id:
        stmt = stmt.where(CareMedicationVersion.medication_id == medication_id)
    result = await session.execute(
        scoped(stmt.order_by(CareMedicationVersion.effective_from.desc()), CareMedicationVersion, scope)
    )
    return list(result.scalars())


async def current_regimen(
    session: AsyncSession, scope: TenantScope, patient_id: str
) -> list[CareMedicationVersion]:
    """ตอบคำถาม 'ตอนนี้ต้องกินยังไง' — active เท่านั้น"""
    await get_patient(session, scope, patient_id, required_scope="medication.read")
    return await _active_versions(session, scope, patient_id)


async def history(
    session: AsyncSession, scope: TenantScope, medication_id: str
) -> list[CareMedicationVersion]:
    """ตอบคำถาม 'เมื่อก่อนกินยังไง' — ทั้ง chain เรียงตามเวลา"""
    result = await session.execute(
        scoped(
            select(CareMedicationVersion)
            .where(CareMedicationVersion.medication_id == medication_id)
            .order_by(CareMedicationVersion.effective_from),
            CareMedicationVersion,
            scope,
        )
    )
    return list(result.scalars())


async def detect_conflicts(session: AsyncSession, scope: TenantScope, patient_id: str) -> list[dict]:
    """หา active version ของยาชื่อเดียวกันมากกว่าหนึ่ง — แล้ว **หยุด ไม่เลือกข้าง**"""
    versions = await _active_versions(session, scope, patient_id)
    by_name: dict[str, list[CareMedicationVersion]] = {}
    for version in versions:
        by_name.setdefault(version.normalized_name, []).append(version)

    conflicts = []
    for name, group in by_name.items():
        if len(group) < 2:
            continue
        for version in group:
            version.status = "needs_reconciliation"
        await session.flush()
        detail = {
            "normalized_name": name,
            "versions": [
                {
                    "version_id": v.version_id,
                    "medication_id": v.medication_id,
                    "prescribed_by": v.prescribed_by,
                    "schedule": v.schedule,
                    "effective_from": v.effective_from.isoformat(),
                }
                for v in group
            ],
        }
        conflicts.append(detail)
        await audit.emit(
            session,
            scope,
            event_type="GOVERNANCE_DECISION",
            subject_type="artifact",
            subject_id=group[0].version_id,
            care_event_type="care.medication.conflict",
            severity="high",
            attributes={
                "record_type": "medication_conflict",
                "patient_id": patient_id,
                # 🔒 ระบบไม่เลือกว่าใบไหนถูก — ส่งข้อเท็จจริงให้คนตัดสิน
                "requires": "reconciliation_by_human",
                **detail,
            },
        )
    return conflicts


async def reconciliation_summary(
    session: AsyncSession, scope: TenantScope, patient_id: str
) -> dict:
    """สรุปยาเพื่อพบหมอ — สร้างจาก chain ที่มีอยู่จริง ไม่เก็บซ้ำ ไม่เติมเนื้อหาเอง"""
    await get_patient(session, scope, patient_id, required_scope="medication.read")
    result = await session.execute(
        scoped(
            select(CareMedicationVersion)
            .where(CareMedicationVersion.patient_id == patient_id)
            .order_by(CareMedicationVersion.effective_from),
            CareMedicationVersion,
            scope,
        )
    )
    versions = list(result.scalars())
    active = [v for v in versions if v.status in ACTIVE_STATUSES]
    return {
        "patient_id": patient_id,
        "active_count": len(active),
        "needs_reconciliation": [v.name for v in versions if v.status == "needs_reconciliation"],
        "stopped": [v.name for v in versions if v.status == "stopped"],
        "changes": [
            {
                "name": v.name,
                "status": v.status,
                "effective_from": v.effective_from.isoformat(),
                "prescribed_by": v.prescribed_by,
                "instruction_source": v.instruction_source,
            }
            for v in versions
        ],
        "current": [
            {"name": v.name, "schedule": v.schedule, "prescribed_by": v.prescribed_by}
            for v in active
        ],
    }


async def doses_for_meal(
    session: AsyncSession, scope: TenantScope, patient_id: str, relation: str
) -> list[dict]:
    """ยาที่ต้องกิน 'ก่อน/หลัง' มื้อนี้ — ลด cognitive load ของผู้ป่วย"""
    if relation not in RELATION_TO_MEAL:
        raise ValueError(f"relation_to_meal ไม่รู้จัก: {relation}")
    doses = []
    for version in await _active_versions(session, scope, patient_id):
        for entry in version.schedule or []:
            if entry.get("relation_to_meal") == relation:
                doses.append(
                    {
                        "name": version.name,
                        "dose": entry.get("dose", ""),
                        "time": entry.get("time", ""),
                        # ยาที่กำลังรอการสะสางต้องไม่บอกจำนวนเม็ดเหมือนปกติ
                        "needs_reconciliation": version.status == "needs_reconciliation",
                    }
                )
    return doses
