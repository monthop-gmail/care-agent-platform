"""นัดหมาย + การเตรียมตัวไปพบหมอ

flow ที่โดเมนนี้ดูแล:
    สร้างนัด → เตือนล่วงหน้า (24h/2h) → เตรียมตัวทีละขั้น → พร้อมออกจากบ้าน
    → พบหมอ → visit brief → บันทึกผลหลังพบหมอ

🔒 ข้อกำหนดทางการแพทย์ (เช่นงดอาหารก่อนตรวจ) ต้องมาจากเอกสารของสถานพยาบาลเท่านั้น
   ห้ามระบบเดาเองว่าต้องงดกี่ชั่วโมง (appointment_rules)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action
from care_addons.ap_tenancy.clock import now
from care_addons.ap_tenancy.ids import new_id
from care_addons.ap_tenancy.services import TenantScope, assert_same_tenant, scoped
from care_addons.care_appointment.models import (
    STEP_KINDS,
    STEPS_REQUIRING_SOURCE,
    CareAppointment,
    CarePreparationStep,
)
from care_addons.care_escalation import services as jobs
from care_addons.care_patient.services import feature_enabled, get_patient

# แผนเตรียมตัวมาตรฐาน: (kind, label, กี่นาทีก่อนเวลานัด, ลำดับ)
# 🔒 ไม่มี fasting_requirement ในนี้ — ต้องเพิ่มเองพร้อมเอกสารเท่านั้น
DEFAULT_PLAN = [
    ("instructions_acknowledged", "รับทราบรายละเอียดการนัด", 15 * 60, 1),
    ("documents_ready", "เตรียมบัตรและเอกสาร", 14 * 60, 2),
    ("clothes_ready", "เตรียมเสื้อผ้าสำหรับพรุ่งนี้", 13 * 60, 3),
    ("medication_ready", "เตรียมยาที่ต้องนำไปด้วย", 120, 4),
    ("transport_ready", "เตรียมการเดินทาง", 90, 5),
    ("ready_to_leave", "พร้อมออกจากบ้าน", 45, 6),
]


class AppointmentNotFound(LookupError):
    pass


class PreparationRuleViolation(PermissionError):
    """กติกาของการเตรียมตัว — โดยเฉพาะข้อกำหนดทางการแพทย์ที่ต้องมีเอกสาร"""


@care_action("appointment.write")
async def create_appointment(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    starts_at: datetime,
    doctor_name: str = "",
    specialty: str | None = None,
    facility: str = "",
    purpose: str = "",
    reminder_offsets_hours: list[int] | None = None,
) -> CareAppointment:
    patient = await get_patient(session, scope, patient_id, required_scope="care.manage")
    if not feature_enabled(patient, "appointment"):
        raise PreparationRuleViolation("care_profile.appointment ยังปิดอยู่สำหรับผู้ป่วยรายนี้")
    if starts_at.tzinfo is None:
        raise ValueError("starts_at ต้องมี timezone — เวลานัดที่ไม่มีโซนทำให้เตือนผิดวันได้")

    appointment = CareAppointment(
        appointment_id=new_id("appt"),
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        starts_at=starts_at,
        doctor_name=doctor_name,
        specialty=specialty,
        facility=facility,
        purpose=purpose,
        reminder_offsets_hours=list(reminder_offsets_hours or [24, 2]),
    )
    session.add(appointment)
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="artifact",
        subject_id=appointment.appointment_id,
        transition={"from": None, "to": "scheduled", "reason": "appointment created"},
        attributes={
            "record_type": "appointment",
            "patient_id": patient_id,
            "starts_at": starts_at.isoformat(),
            "specialty": specialty,
            "purpose": purpose,
        },
    )
    return appointment


async def get_appointment(
    session: AsyncSession, scope: TenantScope, appointment_id: str
) -> CareAppointment:
    result = await session.execute(
        scoped(
            select(CareAppointment).where(CareAppointment.appointment_id == appointment_id),
            CareAppointment,
            scope,
        )
    )
    appointment = result.scalar_one_or_none()
    if appointment is None:
        raise AppointmentNotFound(f"ไม่พบนัดหมาย {appointment_id}")
    assert_same_tenant(scope, appointment)
    return appointment


async def upcoming(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, within_days: int = 30
) -> list[CareAppointment]:
    current = now()
    result = await session.execute(
        scoped(
            select(CareAppointment)
            .where(
                CareAppointment.patient_id == patient_id,
                CareAppointment.starts_at >= current,
                CareAppointment.starts_at <= current + timedelta(days=within_days),
                CareAppointment.status.in_(["scheduled", "preparing", "ready"]),
            )
            .order_by(CareAppointment.starts_at),
            CareAppointment,
            scope,
        )
    )
    return list(result.scalars())


async def schedule_reminders(
    session: AsyncSession, scope: TenantScope, appointment_id: str
) -> list:
    """สร้าง care job สำหรับเตือนล่วงหน้าตาม offsets — เรียกซ้ำได้ ไม่สร้างซ้ำ"""
    appointment = await get_appointment(session, scope, appointment_id)
    created = []
    for offset in appointment.reminder_offsets_hours or []:
        due_at = appointment.starts_at - timedelta(hours=offset)
        existing = await jobs.jobs_for_source(
            session,
            scope,
            source_kind="appointment",
            source_id=appointment.appointment_id,
            due_at=due_at,
        )
        if existing:
            continue
        label = (
            f"นัด{appointment.purpose or 'พบแพทย์'}"
            f"{' กับ ' + appointment.doctor_name if appointment.doctor_name else ''}"
            f" ในอีก {offset} ชั่วโมง"
        )
        created.append(
            await jobs.create_job(
                session,
                scope,
                patient_id=appointment.patient_id,
                source_kind="appointment",
                source_id=appointment.appointment_id,
                label=label,
                due_at=due_at,
                severity="medium",
            )
        )
    return created


@care_action("appointment.prep.write")
async def add_preparation_step(
    session: AsyncSession,
    scope: TenantScope,
    *,
    appointment_id: str,
    kind: str,
    label: str,
    due_at: datetime,
    order: int = 0,
    source_document: str | None = None,
) -> CarePreparationStep:
    if kind not in STEP_KINDS:
        raise ValueError(f"preparation kind ไม่รู้จัก: {kind}")
    if kind in STEPS_REQUIRING_SOURCE and not source_document:
        # 🔒 หัวใจของ appointment_rules — ห้ามระบบสร้างข้อกำหนดทางการแพทย์ขึ้นเอง
        raise PreparationRuleViolation(
            f"ขั้น '{kind}' เป็นข้อกำหนดทางการแพทย์ ต้องอ้าง source_document จากสถานพยาบาล "
            f"— ระบบเดาเองไม่ได้ว่าต้องทำอะไรหรือกี่ชั่วโมง"
        )

    appointment = await get_appointment(session, scope, appointment_id)
    step = CarePreparationStep(
        step_id=new_id("prep"),
        tenant_id=scope.tenant_id,
        patient_id=appointment.patient_id,
        appointment_id=appointment_id,
        kind=kind,
        label=label,
        due_at=due_at,
        order=order,
        source_document=source_document,
    )
    session.add(step)
    await session.flush()
    return step


async def build_default_plan(
    session: AsyncSession, scope: TenantScope, appointment_id: str
) -> list[CarePreparationStep]:
    """สร้างแผนเตรียมตัวมาตรฐาน — ไม่รวมข้อกำหนดทางการแพทย์ใด ๆ"""
    appointment = await get_appointment(session, scope, appointment_id)
    steps = []
    for kind, label, minutes_before, order in DEFAULT_PLAN:
        steps.append(
            await add_preparation_step(
                session,
                scope,
                appointment_id=appointment_id,
                kind=kind,
                label=label,
                due_at=appointment.starts_at - timedelta(minutes=minutes_before),
                order=order,
            )
        )
    appointment.status = "preparing"
    await session.flush()
    return steps


async def start_preparation(
    session: AsyncSession, scope: TenantScope, appointment_id: str
) -> list:
    """เปลี่ยนแผนเตรียมตัวให้เป็น care job — จากนั้น engine เดิมดูแลการเตือน/ส่งต่อให้เอง

    ผู้ป่วยที่ไม่ตอบสนองตามเวลาจะถูก escalate ไป caregiver โดยไม่ต้องเขียน logic ซ้ำ
    """
    steps = await preparation_steps(session, scope, appointment_id)
    created = []
    for step in steps:
        if step.status != "pending":
            continue
        if await jobs.jobs_for_source(
            session, scope, source_kind="appointment", source_id=step.step_id
        ):
            continue
        created.append(
            await jobs.create_job(
                session,
                scope,
                patient_id=step.patient_id,
                source_kind="appointment",
                source_id=step.step_id,
                label=step.label,
                due_at=step.due_at,
                severity="medium",
            )
        )
    return created


async def preparation_steps(
    session: AsyncSession, scope: TenantScope, appointment_id: str
) -> list[CarePreparationStep]:
    result = await session.execute(
        scoped(
            select(CarePreparationStep)
            .where(CarePreparationStep.appointment_id == appointment_id)
            .order_by(CarePreparationStep.order, CarePreparationStep.due_at),
            CarePreparationStep,
            scope,
        )
    )
    return list(result.scalars())


@care_action("appointment.prep.write")
async def complete_step(
    session: AsyncSession,
    scope: TenantScope,
    step_id: str,
    *,
    evidence_kind: str = "patient_confirmed",
) -> CarePreparationStep:
    """ผู้ป่วย/ผู้ดูแลยืนยันว่าทำขั้นนี้แล้ว — ปิด care job ที่ผูกกันด้วย"""
    step = await session.get(CarePreparationStep, step_id)
    if step is None:
        raise AppointmentNotFound(f"ไม่พบขั้นเตรียมตัว {step_id}")
    assert_same_tenant(scope, step)

    step.status = "done"
    step.evidence = {"kind": evidence_kind, "recorded_by": scope.principal.as_dict()}
    await session.flush()

    for job in await jobs.jobs_for_source(
        session, scope, source_kind="appointment", source_id=step_id
    ):
        if job.state not in ("confirmed", "cancelled"):
            await jobs.acknowledge(session, scope, job.care_job_id, evidence_kind=evidence_kind)

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="artifact",
        subject_id=step.step_id,
        care_event_type="care.appointment.prep_step_done",
        evidence=step.evidence,
        transition={"from": "pending", "to": "done", "reason": step.kind},
        attributes={
            "record_type": "preparation_step",
            "patient_id": step.patient_id,
            "appointment_id": step.appointment_id,
            "kind": step.kind,
        },
    )
    await _refresh_readiness(session, scope, step.appointment_id)
    return step


async def _refresh_readiness(session: AsyncSession, scope: TenantScope, appointment_id: str) -> None:
    steps = await preparation_steps(session, scope, appointment_id)
    if steps and all(s.status in ("done", "skipped") for s in steps):
        appointment = await get_appointment(session, scope, appointment_id)
        if appointment.status != "ready":
            appointment.status = "ready"
            await session.flush()
            await audit.emit(
                session,
                scope,
                event_type="STATE_TRANSITION",
                subject_type="artifact",
                subject_id=appointment_id,
                transition={"from": "preparing", "to": "ready", "reason": "เตรียมตัวครบทุกขั้น"},
                attributes={"record_type": "appointment", "patient_id": appointment.patient_id},
            )


async def readiness(session: AsyncSession, scope: TenantScope, appointment_id: str) -> dict:
    """สถานะการเตรียมตัวแบบที่ caregiver เห็น — ข้อเท็จจริงล้วน ไม่ตีความ"""
    appointment = await get_appointment(session, scope, appointment_id)
    steps = await preparation_steps(session, scope, appointment_id)
    outstanding = [s for s in steps if s.status == "pending"]
    return {
        "appointment_id": appointment_id,
        "starts_at": appointment.starts_at,
        "status": appointment.status,
        "total_steps": len(steps),
        "done": sum(1 for s in steps if s.status == "done"),
        "outstanding": [
            {"step_id": s.step_id, "kind": s.kind, "label": s.label, "due_at": s.due_at}
            for s in outstanding
        ],
        "ready_to_leave": appointment.status == "ready",
    }


@care_action("appointment.write")
async def complete_appointment(
    session: AsyncSession, scope: TenantScope, appointment_id: str, *, attended: bool = True
) -> CareAppointment:
    appointment = await get_appointment(session, scope, appointment_id)
    previous = appointment.status
    appointment.status = "completed" if attended else "missed"
    await session.flush()
    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="artifact",
        subject_id=appointment_id,
        care_event_type="care.appointment.completed" if attended else "care.reminder.missed",
        severity="medium" if attended else "high",
        evidence={"kind": "caregiver_confirmed", "recorded_by": scope.principal.as_dict()},
        transition={"from": previous, "to": appointment.status, "reason": "บันทึกผลการไปพบแพทย์"},
        attributes={"record_type": "appointment", "patient_id": appointment.patient_id},
    )
    return appointment


async def visit_brief(session: AsyncSession, scope: TenantScope, appointment_id: str) -> dict:
    """สิ่งที่ควรแจ้ง/ถามคุณหมอ + สรุปยาปัจจุบัน

    🔒 ประกอบจากบันทึกที่มีอยู่จริงเท่านั้น ไม่มีการตีความหรือเติมเนื้อหา
    """
    from care_addons.care_journal.services import visit_brief as journal_brief

    appointment = await get_appointment(session, scope, appointment_id)
    brief = await journal_brief(
        session, scope, appointment.patient_id, specialty=appointment.specialty
    )

    medications: dict = {"available": False, "reason": "ยังไม่ได้เปิดใช้ care_profile.medication"}
    patient = await get_patient(session, scope, appointment.patient_id, required_scope="care.manage")
    if feature_enabled(patient, "medication"):
        from care_addons.care_medication.services import reconciliation_summary

        medications = await reconciliation_summary(session, scope, appointment.patient_id)
        medications["available"] = True

    return {
        "appointment": {
            "appointment_id": appointment_id,
            "starts_at": appointment.starts_at,
            "doctor_name": appointment.doctor_name,
            "specialty": appointment.specialty,
            "purpose": appointment.purpose,
        },
        "observations": brief["observations"],
        "questions": brief["questions"],
        "medications": medications,
        "note": "สร้างจากบันทึกที่มีอยู่จริงเท่านั้น — ไม่มีการตีความทางการแพทย์",
    }


def local_time(appointment: CareAppointment, timezone: str) -> str:
    return appointment.starts_at.astimezone(ZoneInfo(timezone)).strftime("%H:%M")
