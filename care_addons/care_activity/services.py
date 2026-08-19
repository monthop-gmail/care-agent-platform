"""ทำให้งานที่ "เริ่มได้แต่ทำไม่จบ" จบจริง

    S6: เข้าเครื่องซักผ้าแล้วไม่กด start · เครื่องเสร็จแล้วผ้าค้างในเครื่องข้ามคืน

🔒 กติกาของ `contracts/activity/v1` ที่บังคับด้วยโค้ด:
   1. งานที่ **เครื่อง** ทำเสร็จแล้วแต่ผู้ป่วยยังไม่ทำขั้นถัดไป = ยังไม่ completed
   2. ขั้นที่ค้างเกิน `stalled_after_minutes` → `care.task.stalled` → เตือน → ผู้ดูแล
   3. ห้ามสรุปว่า "ผู้ป่วยแย่ลง" จากงานที่ทำไม่จบ — รายงานเป็นจำนวนงานที่ค้างเท่านั้น
   4. ระบบเสนอเวลาที่เหมาะกว่าได้ แต่ **ห้ามบล็อก** ไม่ให้ผู้ป่วยทำ
"""

from __future__ import annotations

from datetime import timedelta

from core.clock import now
from core.tenancy import TenantScope, new_id, scoped
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action
from care_addons.care_activity.models import (
    ACTIVITY_TYPES,
    CONTEXT_CHECKS,
    CareActivity,
    CareActivityStep,
)
from care_addons.care_escalation import services as escalation
from care_addons.care_patient.services import get_patient

SOURCE_KIND = "activity"

OPEN_STATES = ("not_started", "starting", "in_progress", "waiting", "ready_for_next_step", "needs_help")

# workflow ตั้งต้นที่ผู้ดูแล **แก้ได้** — ไม่ใช่สิ่งที่ระบบคิดขึ้นเองแล้วบังคับใช้
# ส่งรายการขั้นตอนมาเองเมื่อไร ตัวนี้ไม่ถูกใช้เลย
DEFAULT_STEPS: dict[str, list[dict]] = {
    "laundry": [
        {"label": "ใส่ผ้าและกดเริ่มเครื่องซัก", "stalled_after_minutes": 30},
        {
            "label": "รอเครื่องซักเสร็จ",
            "awaits_external_event": "washing_machine.finished",
            "stalled_after_minutes": 120,
        },
        {"label": "เอาผ้าออกจากเครื่อง", "stalled_after_minutes": 60},
        {"label": "ตากผ้า", "stalled_after_minutes": 60},
    ],
    "cooking": [
        {"label": "เตรียมของและเปิดเตา", "stalled_after_minutes": 20},
        {"label": "ปิดเตาเมื่อเสร็จ", "stalled_after_minutes": 45},
        {"label": "เก็บของและล้างจาน", "stalled_after_minutes": 60},
    ],
}


class ActivityRuleViolation(PermissionError):
    """กติกาของงานหลายขั้นตอน — ไม่ใช่ error ธรรมดา"""


async def get_activity(
    session: AsyncSession, scope: TenantScope, activity_id: str
) -> CareActivity:
    result = await session.execute(
        scoped(
            select(CareActivity).where(CareActivity.activity_id == activity_id),
            CareActivity,
            scope,
        )
    )
    activity = result.scalars().first()
    if activity is None:
        raise LookupError(f"ไม่พบ activity {activity_id}")
    return activity


async def steps_of(
    session: AsyncSession, scope: TenantScope, activity_id: str
) -> list[CareActivityStep]:
    result = await session.execute(
        scoped(
            select(CareActivityStep)
            .where(CareActivityStep.activity_id == activity_id)
            .order_by(CareActivityStep.order),
            CareActivityStep,
            scope,
        )
    )
    return list(result.scalars())


@care_action("activity.step.record", autonomous=True)
async def start_activity(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    activity_type: str,
    label: str = "",
    steps: list[dict] | None = None,
    context_checks: list[str] | None = None,
) -> CareActivity:
    """เริ่มงาน — ขั้นแรกกลายเป็น care job ทันที ขั้นถัดไปเกิดเมื่อขั้นก่อนหน้าเสร็จ"""
    await get_patient(session, scope, patient_id, required_scope="care.manage")
    if activity_type not in ACTIVITY_TYPES:
        raise ValueError(f"activity_type ไม่รู้จัก: {activity_type}")

    plan = steps if steps is not None else DEFAULT_STEPS.get(activity_type)
    if not plan:
        raise ValueError(
            f"ไม่มีขั้นตอนสำหรับ '{activity_type}' — ส่ง steps มาด้วย "
            f"(ระบบไม่คิดขั้นตอนเองสำหรับงานที่ไม่มี workflow ตั้งต้น)"
        )
    for check in context_checks or []:
        if check not in CONTEXT_CHECKS:
            raise ValueError(f"context_check ไม่รู้จัก: {check}")

    activity = CareActivity(
        activity_id=new_id("act"),
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        activity_type=activity_type,
        label=label or activity_type,
        state="in_progress",
        context_checks=list(context_checks) if context_checks else None,
        correlation_id=scope.correlation_id or new_id("corr"),
        started_at=now(),
    )
    session.add(activity)
    await session.flush()

    for index, raw in enumerate(plan):
        if not raw.get("label"):
            raise ValueError("ทุกขั้นต้องมี label — ผู้ป่วยต้องอ่านแล้วรู้ว่าต้องทำอะไร")
        session.add(
            CareActivityStep(
                step_id=new_id("stp"),
                tenant_id=scope.tenant_id,
                patient_id=patient_id,
                activity_id=activity.activity_id,
                label=raw["label"],
                order=index,
                state="not_started",
                awaits_external_event=raw.get("awaits_external_event"),
                stalled_after_minutes=int(raw.get("stalled_after_minutes", 60)),
            )
        )
    await session.flush()

    await audit.emit(
        session,
        _activity_scope(scope, activity),
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=activity.activity_id,
        severity="low",
        transition={"to": "in_progress", "reason": "เริ่มงาน"},
        attributes={
            "record_type": "activity",
            "patient_id": patient_id,
            "activity_type": activity_type,
            "steps": len(plan),
        },
    )
    await _activate_next_step(session, scope, activity)
    return activity


def _activity_scope(scope: TenantScope, activity: CareActivity) -> TenantScope:
    """ทุก event ของงานเดียวกันใช้ correlation_id เดียวกัน — trail อ่านต่อเนื่องได้"""
    if scope.correlation_id == activity.correlation_id:
        return scope
    return TenantScope(
        tenant_id=scope.tenant_id,
        principal=scope.principal,
        workspace_id=scope.workspace_id,
        correlation_id=activity.correlation_id,
    )


async def _activate_next_step(
    session: AsyncSession, scope: TenantScope, activity: CareActivity
) -> CareActivityStep | None:
    """ทำให้ขั้นถัดไปเป็นงานที่มีเวลาจริง — ขั้นที่รอเครื่องไม่สร้าง reminder ให้ผู้ป่วย"""
    steps = await steps_of(session, scope, activity.activity_id)
    pending = [s for s in steps if s.state not in ("completed", "abandoned")]
    if not pending:
        await _complete_activity(session, scope, activity)
        return None

    step = pending[0]
    step.started_at = now()
    job_scope = _activity_scope(scope, activity)

    if step.awaits_external_event:
        # 🔒 ขั้นที่รอสัญญาณจากเครื่อง — ไม่เตือนผู้ป่วยตอนนี้ เพราะเขาทำอะไรไม่ได้
        #    แต่ต้องมีนาฬิกาจับเวลาไว้ ถ้าเงียบเกินกำหนดถือว่าค้าง (sweep_stalled)
        step.state = "waiting"
        await session.flush()
        await audit.emit(
            session,
            job_scope,
            event_type="STATE_TRANSITION",
            subject_type="record",
            subject_id=step.step_id,
            severity="low",
            transition={"from": "not_started", "to": "waiting", "reason": step.awaits_external_event},
            attributes={
                "record_type": "activity_step",
                "patient_id": activity.patient_id,
                "activity_id": activity.activity_id,
                "awaits_external_event": step.awaits_external_event,
            },
        )
        return step

    step.state = "in_progress"
    job = await escalation.create_job(
        session,
        job_scope,
        patient_id=activity.patient_id,
        source_kind=SOURCE_KIND,
        source_id=step.step_id,
        label=step.label,
        due_at=now(),
        severity="medium",
    )
    step.care_job_id = job.care_job_id
    activity.state = "in_progress"
    await session.flush()
    return step


async def _complete_activity(
    session: AsyncSession, scope: TenantScope, activity: CareActivity
) -> None:
    activity.state = "completed"
    activity.completed_at = now()
    await session.flush()
    await audit.emit(
        session,
        _activity_scope(scope, activity),
        event_type="JOB_COMPLETED",
        subject_type="record",
        subject_id=activity.activity_id,
        care_event_type="care.task.step_completed",
        severity="low",
        transition={"from": "in_progress", "to": "completed", "reason": "ครบทุกขั้น"},
        attributes={
            "record_type": "activity",
            "patient_id": activity.patient_id,
            "activity_type": activity.activity_type,
        },
    )


@care_action("activity.step.record", autonomous=True)
async def complete_step(
    session: AsyncSession,
    scope: TenantScope,
    step_id: str,
    *,
    evidence_kind: str = "patient_confirmed",
) -> CareActivityStep:
    """ผู้ป่วย/ผู้ดูแลยืนยันว่าทำขั้นนี้แล้ว — ต้องมี evidence เสมอ ห้ามอนุมานเอง"""
    result = await session.execute(
        scoped(
            select(CareActivityStep).where(CareActivityStep.step_id == step_id),
            CareActivityStep,
            scope,
        )
    )
    step = result.scalars().first()
    if step is None:
        raise LookupError(f"ไม่พบขั้นตอน {step_id}")
    if step.state == "completed":
        return step

    activity = await get_activity(session, scope, step.activity_id)
    previous = step.state
    step.state = "completed"
    step.completed_at = now()
    step.evidence = {"kind": evidence_kind, "recorded_by": scope.principal.as_dict()}
    await session.flush()

    if step.care_job_id:
        try:
            await escalation.acknowledge(
                session, scope, step.care_job_id, evidence_kind=evidence_kind
            )
        except LookupError:
            pass

    await audit.emit(
        session,
        _activity_scope(scope, activity),
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=step.step_id,
        care_event_type="care.task.step_completed",
        severity="low",
        evidence=step.evidence,
        transition={"from": previous, "to": "completed", "reason": "ยืนยันว่าทำแล้ว"},
        attributes={
            "record_type": "activity_step",
            "patient_id": step.patient_id,
            "activity_id": step.activity_id,
            "label": step.label,
        },
    )
    await _activate_next_step(session, scope, activity)
    return step


async def external_signal(
    session: AsyncSession,
    scope: TenantScope,
    *,
    activity_id: str,
    event: str,
    source_system: str,
) -> CareActivityStep | None:
    """เครื่องแจ้งว่าทำงานเสร็จ — 🔒 **งานยังไม่จบ** จนกว่าคนจะทำขั้นถัดไป

    นี่คือหัวใจของ activity_rules ข้อ 1: ผ้าที่ซักเสร็จแต่ยังอยู่ในเครื่องคือปัญหา
    ที่ระบบต้องเห็น ไม่ใช่ความสำเร็จที่ระบบฉลอง
    """
    activity = await get_activity(session, scope, activity_id)
    steps = await steps_of(session, scope, activity_id)
    waiting = next(
        (s for s in steps if s.state == "waiting" and s.awaits_external_event == event), None
    )
    if waiting is None:
        return None

    waiting.state = "completed"
    waiting.completed_at = now()
    waiting.evidence = {"kind": "device_reported", "recorded_by": {"type": "service", "id": source_system}}
    await session.flush()

    await audit.emit(
        session,
        _activity_scope(scope, activity),
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=waiting.step_id,
        care_event_type="care.task.step_completed",
        severity="low",
        source_kind="external",            # 🔒 มาจากข้างนอก ต้องรู้ตลอดไป (event/v1)
        source_system=source_system,
        evidence=waiting.evidence,
        transition={"from": "waiting", "to": "completed", "reason": event},
        attributes={
            "record_type": "activity_step",
            "patient_id": activity.patient_id,
            "activity_id": activity_id,
            "device_event": event,
        },
    )
    # ขั้นถัดไปเป็นของ **คน** เสมอ — เครื่องเสร็จแค่แปลว่าถึงคิวคนแล้ว
    return await _activate_next_step(session, scope, activity)


async def sweep_stalled(session: AsyncSession, scope: TenantScope) -> int:
    """ขั้นที่ค้างเกินกำหนด → `care.task.stalled` + ส่งต่อผู้ดูแล

    🔒 รายงานเป็น "ขั้นนี้ค้างมา N นาที" เท่านั้น — ห้ามตีความว่าผู้ป่วยแย่ลง (ข้อ 3)
    """
    moment = now()
    result = await session.execute(
        scoped(
            select(CareActivityStep).where(
                CareActivityStep.state.in_(["in_progress", "waiting"]),
                CareActivityStep.stalled_reported_at.is_(None),
            ),
            CareActivityStep,
            scope,
        )
    )
    reported = 0
    for step in result.scalars():
        started = step.started_at
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=moment.tzinfo)
        stalled_for = moment - started
        if stalled_for < timedelta(minutes=step.stalled_after_minutes):
            continue

        activity = await get_activity(session, scope, step.activity_id)
        step.stalled_reported_at = moment
        step.state = "needs_help"
        activity.state = "needs_help"
        await session.flush()

        job_scope = _activity_scope(scope, activity)
        await audit.emit(
            session,
            job_scope,
            event_type="STATE_TRANSITION",
            subject_type="record",
            subject_id=step.step_id,
            care_event_type="care.task.stalled",
            severity="medium",
            transition={"to": "needs_help", "reason": "ค้างเกินเวลาที่ตั้งไว้"},
            attributes={
                "record_type": "activity_step",
                "patient_id": step.patient_id,
                "activity_id": step.activity_id,
                "label": step.label,
                "stalled_minutes": int(stalled_for.total_seconds() // 60),
            },
        )
        await escalation.send_to_caregivers(
            session,
            job_scope,
            patient_id=step.patient_id,
            text=(
                f"{activity.label}: ขั้น '{step.label}' ค้างมา "
                f"{int(stalled_for.total_seconds() // 60)} นาทีแล้ว"
            ),
            capability="caregiver.notify",
            severity="medium",
        )
        reported += 1
    return reported


async def open_activities(
    session: AsyncSession, scope: TenantScope, patient_id: str
) -> list[CareActivity]:
    result = await session.execute(
        scoped(
            select(CareActivity)
            .where(CareActivity.patient_id == patient_id, CareActivity.state.in_(OPEN_STATES))
            .order_by(CareActivity.created_at),
            CareActivity,
            scope,
        )
    )
    return list(result.scalars())


async def as_activity(
    session: AsyncSession, scope: TenantScope, activity: CareActivity
) -> dict:
    """payload ตาม `contracts/activity/v1`"""
    steps = await steps_of(session, scope, activity.activity_id)
    payload = {
        "activity_id": activity.activity_id,
        "tenant_id": activity.tenant_id,
        "patient_id": activity.patient_id,
        "activity_type": activity.activity_type,
        "state": activity.state,
        "steps": [
            {
                "step_id": s.step_id,
                "label": s.label,
                "state": s.state,
                **({"awaits_external_event": s.awaits_external_event} if s.awaits_external_event else {}),
                "stalled_after_minutes": s.stalled_after_minutes,
            }
            for s in steps
        ],
    }
    if activity.context_checks:
        payload["context_checks"] = activity.context_checks
    return payload
