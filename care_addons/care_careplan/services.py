"""คำสั่งหลังพบหมอ → งานที่เกิดซ้ำจริง

    "เดินวันละ 20 นาที · ดื่มน้ำวันละ 8 แก้ว · ทายาที่เข่าเช้า-เย็น · กลับมาตรวจอีก 2 สัปดาห์"

คำแนะนำที่พูดในห้องตรวจ 30 วินาที คือสิ่งที่ผู้ป่วยความจำถดถอยลืมภายในวันเดียว
โมดูลนี้ทำให้มันกลายเป็นงานที่มีเวลา มีการยืนยัน และตรวจย้อนได้ว่าทำจริงแค่ไหน

🔒 กติกาของ `contracts/careplan/v1` ที่บังคับด้วยโค้ด:
   1. AI สร้างได้แค่ `proposed` — ต้องมีคนยืนยันจึง `active`
   2. รายงาน adherence อิงบันทึกจริงเท่านั้น · ไม่มีบันทึก = บอกว่าไม่มีข้อมูลเพียงพอ
   3. ห้ามระบบออกแบบ diet/exercise เอง — เก็บตามคำสั่งที่ได้รับ
      (ไม่มีฟังก์ชันไหนในไฟล์นี้ที่ "สร้าง" เนื้อหาคำสั่ง มีแต่ที่จดสิ่งที่ผู้เรียกส่งมา)
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.clock import now
from core.tenancy import Principal, TenantScope, new_id, scoped
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_approval import services as approvals
from care_addons.ap_audit import services as audit
from care_addons.ap_policy.engine import evaluate
from care_addons.ap_policy.services import care_action
from care_addons.care_careplan.models import (
    FREQUENCY_TYPES,
    SOURCE_KINDS,
    STANDING_INSTRUCTION_TYPES,
    TASK_TYPES,
    CareCarePlanTask,
)
from care_addons.care_escalation import services as escalation
from care_addons.care_escalation.models import CareJob
from care_addons.care_escalation.services import create_job
from care_addons.care_patient.services import get_patient

SOURCE_KIND = "careplan"

# เวลาเริ่มต้นเมื่อผู้สั่งไม่ได้ระบุ — เลือกให้ห่างกันพอที่จะไม่กลายเป็นการเตือนรัวติดกัน
DEFAULT_TIMES = ["09:00", "13:00", "17:00", "20:00"]


class CarePlanRuleViolation(PermissionError):
    """กติกาของ care plan — ไม่ใช่ error ธรรมดา ต้องอ่านข้อความให้ครบก่อนแก้"""


def _validate_frequency(frequency: dict) -> dict:
    if not isinstance(frequency, dict) or frequency.get("type") not in FREQUENCY_TYPES:
        raise ValueError(f"frequency.type ต้องเป็นหนึ่งใน {FREQUENCY_TYPES}")
    cleaned = {"type": frequency["type"]}
    if cleaned["type"] == "times_per_day":
        times = frequency.get("times")
        if not isinstance(times, int) or times < 1:
            raise ValueError("frequency.times ต้องเป็นจำนวนครั้งต่อวัน (>= 1)")
        cleaned["times"] = times
    elif frequency.get("times") is not None:
        cleaned["times"] = frequency["times"]
    return cleaned


def _validate_times(values: list[str] | None, frequency: dict, task_type: str) -> list[str]:
    """เวลาที่จะเตือนจริง — ไม่ระบุมาก็เดาเวลาให้ แต่ **ไม่เดาจำนวนครั้ง**

    จำนวนครั้งเป็นคำสั่งของหมอ · เวลาเป็นความสะดวกของครอบครัว — เดาได้เฉพาะอย่างหลัง
    """
    if task_type in STANDING_INSTRUCTION_TYPES or frequency["type"] == "ongoing":
        return []
    if values:
        for value in values:
            hour, _, minute = str(value).partition(":")
            if not (hour.isdigit() and minute.isdigit() and 0 <= int(hour) < 24 and 0 <= int(minute) < 60):
                raise ValueError(f"เวลาไม่ถูกรูปแบบ HH:MM: {value!r}")
        return list(values)

    count = frequency.get("times", 1) if frequency["type"] == "times_per_day" else 1
    if count > len(DEFAULT_TIMES):
        step = timedelta(hours=14) / max(count - 1, 1)
        start = datetime.combine(date(2000, 1, 1), time(8, 0))
        return [(start + step * i).strftime("%H:%M") for i in range(count)]
    return DEFAULT_TIMES[:count]


def _validate_source(source: dict) -> dict:
    if not isinstance(source, dict) or source.get("kind") not in SOURCE_KINDS:
        raise ValueError(f"source.kind ต้องเป็นหนึ่งใน {SOURCE_KINDS} — ต้องรู้เสมอว่าคำสั่งมาจากไหน")
    return {k: v for k, v in source.items() if v is not None}


@care_action("careplan.task.write", autonomous=True)
async def propose_task(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    task_type: str,
    description: str,
    frequency: dict,
    source: dict,
    scheduled_times: list[str] | None = None,
    duration_minutes: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    severity: str = "medium",
    source_document: str | None = None,
) -> CareCarePlanTask:
    """จดคำสั่งที่ได้รับ — ได้แค่ `proposed` เท่านั้น ต่อให้ผู้เรียกเป็นคน

    เหตุผลเดียวกับ medication: agent ถอดความจากหมอได้ แต่ยืนยันแทนคนไม่ได้
    (careplan/v1 กติกาข้อ 1) · การยืนยันไปอยู่ที่คิวรออนุมัติ (ADR-0009)
    """
    patient = await get_patient(session, scope, patient_id, required_scope="care.manage")
    if task_type not in TASK_TYPES:
        raise ValueError(f"task_type ไม่รู้จัก: {task_type} — ต้องเป็นหนึ่งใน {TASK_TYPES}")
    if not description.strip():
        raise ValueError("description ว่างไม่ได้ — ต้องจดว่าหมอสั่งอะไรไว้ตามถ้อยคำที่ได้รับ")

    freq = _validate_frequency(frequency)
    times = _validate_times(scheduled_times, freq, task_type)
    tz = ZoneInfo(patient.timezone or "Asia/Bangkok")

    task = CareCarePlanTask(
        task_id=new_id("cpt"),
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        task_type=task_type,
        description=description.strip(),
        duration_minutes=duration_minutes,
        frequency=freq,
        scheduled_times=times,
        source=_validate_source(source),
        start_date=start_date or now().astimezone(tz).date(),
        end_date=end_date,
        status="proposed",
        severity=severity,
        created_at=now(),
        created_by=scope.principal.as_dict(),
        source_document=source_document,
        reminders_enabled=bool(times),
    )
    session.add(task)
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=task.task_id,
        care_event_type="care.careplan.changed",
        severity="low",   # แค่ข้อเสนอ ยังไม่มีผลกับสิ่งที่ผู้ป่วยต้องทำ
        transition={"to": "proposed", "reason": "จดคำสั่งหลังพบหมอ"},
        attributes={
            "record_type": "careplan_task",
            "patient_id": patient_id,
            "task_type": task_type,
            "frequency": freq["type"],
            "source_kind": task.source["kind"],
        },
    )

    # เข้าคิวรอคนยืนยัน — ค้างได้ตลอดกาล ไม่มี auto-approve (ADR-0009)
    await approvals.request_approval(
        session,
        scope,
        decision=evaluate("careplan.task.activate"),
        subject_type="artifact",
        subject_id=task.task_id,
        summary=f"ยืนยันคำสั่งหลังพบหมอ: {task.description}",
        proposed={
            "task_type": task_type,
            "description": task.description,
            "frequency": freq,
            "scheduled_times": times,
            "duration_minutes": duration_minutes,
            "source": task.source,
            "start_date": task.start_date.isoformat(),
            "end_date": end_date.isoformat() if end_date else None,
        },
        requested_by=scope.principal.as_dict(),
        correlation_id=scope.correlation_id,
    )
    return task


@care_action("careplan.task.activate", autonomous=False)
async def activate_task(
    session: AsyncSession,
    scope: TenantScope,
    task_id: str,
    *,
    activated_by: Principal,
    decision=None,
) -> CareCarePlanTask:
    """ทำให้คำสั่งมีผลจริง — **คนเท่านั้นที่ทำได้** (careplan/v1 กติกาข้อ 1)"""
    if activated_by.type != "human":
        raise CarePlanRuleViolation(
            f"ผู้ยืนยันต้องเป็นคน — ได้รับ principal type '{activated_by.type}' "
            f"(careplan/v1: AI สร้างได้แค่ proposed)"
        )
    task = await get_task(session, scope, task_id)
    if task.status not in ("proposed", "paused"):
        raise CarePlanRuleViolation(
            f"ทำให้ active ได้เฉพาะงานที่ยัง proposed หรือ paused — ตอนนี้เป็น '{task.status}'"
        )

    previous = task.status
    task.status = "active"
    task.activated_by = activated_by.as_dict()
    task.activated_at = now()
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=task.task_id,
        care_event_type="care.careplan.changed",
        severity="medium",   # ตั้งแต่วินาทีนี้ผู้ป่วยจะถูกเตือนให้ทำจริง
        policy_result=decision.as_policy_result() if decision else None,
        evidence={"kind": "caregiver_confirmed", "recorded_by": activated_by.as_dict()},
        transition={"from": previous, "to": "active", "reason": "ยืนยันคำสั่งหลังพบหมอ"},
        attributes={
            "record_type": "careplan_task",
            "patient_id": task.patient_id,
            "task_type": task.task_type,
        },
    )

    # ยืนยันตรง ๆ โดยไม่ผ่านคิว = เรื่องจบไปทางอื่นแล้ว คำขอที่ค้างไม่ต้องตัดสินซ้ำ
    for pending in await approvals.pending_for_subject(
        session, scope, subject_type="artifact", subject_id=task.task_id
    ):
        await approvals.withdraw(
            session,
            scope,
            request_id=pending.request_id,
            reason="ยืนยันโดยตรงโดยผู้ดูแลที่มีอำนาจแล้ว",
            by=activated_by.as_dict(),
        )
    return task


async def _apply_approved_task(session, scope, request, approval) -> None:
    """อนุมัติแล้ว = คนสั่งจริง → คำสั่งมีผลในชื่อของคนที่ตัดสิน"""
    await activate_task(
        session,
        scope,
        request.subject_id,
        activated_by=Principal(
            type=approval.authority["type"],
            id=approval.authority["id"],
            display_name=approval.authority.get("display_name", ""),
        ),
    )


approvals.register_applier("careplan.task.activate", _apply_approved_task)


@care_action("careplan.task.write", autonomous=True)
async def set_status(
    session: AsyncSession,
    scope: TenantScope,
    task_id: str,
    *,
    status: str,
    reason: str,
) -> CareCarePlanTask:
    """หยุดชั่วคราว / จบแล้ว / ยกเลิก — ทางเดียวที่ status เปลี่ยนโดยไม่ต้องยืนยันใหม่

    🔒 ไม่รับ `active` ที่นี่ — การทำให้คำสั่งมีผลต้องผ่าน `activate_task` ซึ่งบังคับว่าต้องมีคน
    """
    if status not in ("paused", "completed", "cancelled"):
        raise CarePlanRuleViolation(
            f"เปลี่ยนเป็น '{status}' ที่นี่ไม่ได้ — active ต้องผ่าน activate_task ที่บังคับว่าต้องมีคน"
        )
    if not reason.strip():
        raise ValueError("reason ว่างไม่ได้ — ต้องตอบได้ว่าหยุดคำสั่งของหมอเพราะอะไร")

    task = await get_task(session, scope, task_id)
    previous = task.status
    if previous == status:
        return task
    task.status = status
    await session.flush()

    # 🔒 หยุดคำสั่งต้องหยุดสิ่งที่ค้างอยู่ด้วย — งานของวันนี้ถูกสร้างไว้ก่อนแล้ว
    #    ถ้าไม่ยกเลิก ผู้ป่วยจะยังถูกเตือนให้ทำสิ่งที่หมอสั่งให้หยุดไปจนหมดวัน
    cancelled = await escalation.cancel_jobs(
        session,
        scope,
        source_kind=SOURCE_KIND,
        source_id=task.task_id,
        reason=f"คำสั่งถูกเปลี่ยนเป็น '{status}': {reason.strip()}",
    )

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=task.task_id,
        care_event_type="care.careplan.changed",
        severity="medium",
        evidence={"kind": "caregiver_confirmed", "recorded_by": scope.principal.as_dict()},
        transition={"from": previous, "to": status, "reason": reason.strip()},
        attributes={
            "record_type": "careplan_task",
            "patient_id": task.patient_id,
            "task_type": task.task_type,
            "cancelled_jobs": len(cancelled),
        },
    )
    return task


async def get_task(session: AsyncSession, scope: TenantScope, task_id: str) -> CareCarePlanTask:
    result = await session.execute(
        scoped(select(CareCarePlanTask).where(CareCarePlanTask.task_id == task_id), CareCarePlanTask, scope)
    )
    task = result.scalars().first()
    if task is None:
        raise LookupError(f"ไม่พบ care plan task {task_id}")
    return task


async def list_tasks(
    session: AsyncSession,
    scope: TenantScope,
    patient_id: str,
    *,
    statuses: list[str] | None = None,
) -> list[CareCarePlanTask]:
    stmt = select(CareCarePlanTask).where(CareCarePlanTask.patient_id == patient_id)
    if statuses:
        stmt = stmt.where(CareCarePlanTask.status.in_(statuses))
    result = await session.execute(
        scoped(stmt.order_by(CareCarePlanTask.created_at), CareCarePlanTask, scope)
    )
    return list(result.scalars())


def occurs_on(task: CareCarePlanTask, day: date) -> bool:
    """คำสั่งนี้ต้องทำในวันนั้นไหม — ตัดสินจากช่วงวันที่และความถี่ที่หมอสั่งเท่านั้น"""
    if task.status != "active" or not task.reminders_enabled or not task.scheduled_times:
        return False
    if day < task.start_date or (task.end_date and day > task.end_date):
        return False
    kind = (task.frequency or {}).get("type")
    if kind in ("daily", "times_per_day"):
        return True
    if kind == "weekly":
        return day.weekday() == task.start_date.weekday()
    if kind == "once":
        return day == task.start_date
    return False


async def materialize_day(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, for_date: date | None = None
) -> list[CareJob]:
    """สร้าง care job ของวันนั้นจากคำสั่งที่ active — เรียกซ้ำได้ ไม่สร้างซ้ำ (idempotent)"""
    patient = await get_patient(session, scope, patient_id, required_scope="care.manage")
    tz = ZoneInfo(patient.timezone or "Asia/Bangkok")
    day = for_date or now().astimezone(tz).date()

    created: list[CareJob] = []
    for task in await list_tasks(session, scope, patient_id, statuses=["active"]):
        if not occurs_on(task, day):
            continue
        for slot in task.scheduled_times:
            hour, _, minute = slot.partition(":")
            due_at = datetime.combine(day, time(int(hour), int(minute)), tzinfo=tz).astimezone(
                ZoneInfo("UTC")
            )
            existing = await session.execute(
                scoped(
                    select(CareJob).where(
                        CareJob.source_kind == SOURCE_KIND,
                        CareJob.source_id == task.task_id,
                        CareJob.due_at == due_at,
                    ),
                    CareJob,
                    scope,
                )
            )
            if existing.scalars().first() is not None:
                continue
            created.append(
                await create_job(
                    session,
                    scope,
                    patient_id=patient_id,
                    source_kind=SOURCE_KIND,
                    source_id=task.task_id,
                    label=_job_label(task),
                    due_at=due_at,
                    severity=task.severity,
                )
            )
    return created


def _job_label(task: CareCarePlanTask) -> str:
    if task.duration_minutes:
        return f"{task.description} ({task.duration_minutes} นาที)"
    return task.description


async def adherence(
    session: AsyncSession, scope: TenantScope, task_id: str, *, days: int = 7
) -> dict:
    """ทำตามคำสั่งได้แค่ไหน — 🔒 นับจากบันทึกจริงเท่านั้น (careplan/v1 กติกาข้อ 2)

    ไม่มีบันทึก = **บอกว่าไม่มีข้อมูลเพียงพอ** ไม่ใช่รายงาน 0% ซึ่งอ่านเหมือน "ไม่ได้ทำเลย"
    ความต่างนี้สำคัญ เพราะ 0% ทำให้ผู้ดูแลตัดสินใจผิดได้ ส่วน "ไม่มีข้อมูล" ทำให้ไปหาข้อมูลต่อ
    """
    task = await get_task(session, scope, task_id)
    since = now() - timedelta(days=days)
    result = await session.execute(
        scoped(
            select(CareJob).where(
                CareJob.source_kind == SOURCE_KIND,
                CareJob.source_id == task_id,
                CareJob.due_at >= since,
                CareJob.due_at <= now(),
            ),
            CareJob,
            scope,
        )
    )
    jobs = list(result.scalars())
    if not jobs:
        return {
            "task_id": task_id,
            "window_days": days,
            "available": False,
            "reason": "ยังไม่มีบันทึกในช่วงนี้ — ข้อมูลไม่พอจะบอกว่าทำตามคำสั่งได้แค่ไหน",
        }

    confirmed = [j for j in jobs if j.state == "confirmed"]
    missed = [j for j in jobs if j.state in ("missed", "escalated")]
    return {
        "task_id": task_id,
        "description": task.description,
        "window_days": days,
        "available": True,
        "due": len(jobs),
        "confirmed": len(confirmed),
        "missed": len(missed),
        "open": len(jobs) - len(confirmed) - len(missed),
        "note": "นับจากการยืนยันที่บันทึกไว้เท่านั้น — ไม่ได้ยืนยันไม่ได้แปลว่าไม่ได้ทำ",
    }


def as_careplan_task(task: CareCarePlanTask) -> dict:
    """payload ตาม `contracts/careplan/v1` — ใช้ส่งออกนอกระบบและให้ payload_check validate"""
    payload: dict = {
        "task_id": task.task_id,
        "tenant_id": task.tenant_id,
        "patient_id": task.patient_id,
        "task_type": task.task_type,
        "description": task.description,
        "frequency": task.frequency,
        "source": task.source,
        "start_date": task.start_date.isoformat(),
        "end_date": task.end_date.isoformat() if task.end_date else None,
        "status": task.status,
    }
    if task.duration_minutes is not None:
        payload["duration_minutes"] = task.duration_minutes
    return payload
