"""Care job engine — closed loop ที่ทำให้ reminder ไม่ใช่แค่ notification

    ถึงเวลา → JOB_CREATED
       ↓ ส่ง reminder (EXECUTION_STARTED + care.reminder.sent)
    ผู้ป่วยตอบ? ─yes→ confirmed → JOB_COMPLETED
       │ no
       ↓ backoff → เตือนซ้ำจนครบ max_attempts (ครั้งสุดท้ายถามตรง ๆ)
    missed → GOVERNANCE_DECISION → care.escalated → caregiver

🔒 ไม่มีจุดไหนที่ระบบเดาแทนผู้ป่วย — ไม่มีหลักฐาน = ยังไม่ยืนยัน (ADR-0006 ข้อ 5)
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.engine import PolicyDenied, evaluate
from care_addons.ap_tenancy.clock import now
from care_addons.ap_tenancy.ids import new_id
from care_addons.ap_tenancy.services import TenantScope, assert_same_tenant, scoped
from care_addons.care_escalation import policy as escalation_policy
from care_addons.care_escalation.models import CareJob, CareNotification
from care_addons.care_patient.services import care_team, get_patient

logger = logging.getLogger(__name__)

# ช่องทางที่ส่งข้อความออกได้จริง — addon ของช่องทาง (เช่น care_line) ลงทะเบียนตัวเองที่นี่
# ค่าเริ่มต้นไม่มีใครลงทะเบียน = ข้อความถูกบันทึกไว้ใน DB อย่างเดียว (โหมด PoC)
_SENDERS: dict[str, Any] = {}


def register_sender(channel: str, sender: Any) -> None:
    """ลงทะเบียนตัวส่งของช่องทางหนึ่ง

    sender(session, notification) -> (ok: bool, error: str | None)
    ต้องไม่ raise — ช่องทางล่มต้องไม่ทำให้ care loop ทั้งวงหยุด
    """
    _SENDERS[channel] = sender


def sender_for(channel: str):
    return _SENDERS.get(channel)

# capability ต่อชนิดของงาน — ใช้ประเมิน policy ก่อนส่งทุกครั้ง
SEND_CAPABILITY = {
    "routine": "routine.reminder.send",
    "meal": "meal.reminder.send",
    "medication": "medication.reminder.send",
    "appointment": "appointment.reminder.send",
    "careplan": "routine.reminder.send",
    "activity": "routine.reminder.send",
    "safety": "emergency.escalate",
}

CONFIRMED_EVENT = {
    "meal": "care.meal.confirmed",
    "medication": "care.medication.confirmed",
    # 🔒 ไม่ map appointment ที่นี่ — "รับทราบว่ามีนัด" ไม่ได้แปลว่า "ไปพบหมอมาแล้ว"
    #    care.appointment.completed ออกได้จาก care_appointment.complete_appointment() เท่านั้น
}
MISSED_EVENT = {
    "meal": "care.meal.missed",
    "medication": "care.medication.missed",
}
SENT_EVENT = {"appointment": "care.appointment.reminded"}


class JobNotFound(LookupError):
    pass


def _tz(patient) -> ZoneInfo:
    try:
        return ZoneInfo(patient.timezone or "Asia/Bangkok")
    except Exception:
        return ZoneInfo("Asia/Bangkok")


def _parse_hhmm(value: str) -> time:
    hour, _, minute = value.partition(":")
    return time(int(hour), int(minute))


def in_quiet_hours(patient, when: datetime) -> bool:
    if not patient.quiet_hours_start or not patient.quiet_hours_end:
        return False
    local = when.astimezone(_tz(patient)).time()
    start = _parse_hhmm(patient.quiet_hours_start)
    end = _parse_hhmm(patient.quiet_hours_end)
    if start <= end:
        return start <= local < end
    return local >= start or local < end  # คร่อมเที่ยงคืน


def quiet_hours_end(patient, when: datetime) -> datetime:
    """เวลาที่ออกจากช่วงห้ามรบกวน (UTC) — เลื่อน reminder ไปตอนนั้นแทนที่จะข้ามไปเลย"""
    tz = _tz(patient)
    local = when.astimezone(tz)
    end = _parse_hhmm(patient.quiet_hours_end)
    candidate = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(when.tzinfo or ZoneInfo("UTC"))


async def create_job(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    source_kind: str,
    source_id: str,
    label: str,
    due_at: datetime,
    severity: str = "medium",
    max_attempts: int | None = None,
) -> CareJob:
    pol = escalation_policy.load()
    correlation_id = scope.correlation_id or new_id("corr")
    job = CareJob(
        care_job_id=new_id("job"),
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        source_kind=source_kind,
        source_id=source_id,
        label=label,
        due_at=due_at,
        severity=severity,
        max_attempts=max_attempts or pol.max_attempts,
        next_attempt_at=due_at,
        correlation_id=correlation_id,
    )
    session.add(job)
    await session.flush()

    job_scope = _job_scope(scope, job)
    await audit.emit(
        session,
        job_scope,
        event_type="JOB_CREATED",
        subject_type="job",
        subject_id=job.care_job_id,
        job_id=job.care_job_id,
        severity=severity,
        attributes={
            "patient_id": patient_id,
            "source_kind": source_kind,
            "source_id": source_id,
            "label": label,
            "due_at": due_at.isoformat(),
        },
    )
    return job


def _job_scope(scope: TenantScope, job: CareJob) -> TenantScope:
    """ทุก event ของรอบเดียวกันใช้ correlation_id เดียวกัน — เพื่อรวมเป็นการแจ้งครั้งเดียว"""
    if scope.correlation_id == job.correlation_id:
        return scope
    return TenantScope(
        tenant_id=scope.tenant_id,
        principal=scope.principal,
        workspace_id=scope.workspace_id,
        correlation_id=job.correlation_id,
    )


async def _transition(
    session: AsyncSession,
    scope: TenantScope,
    job: CareJob,
    to_state: str,
    reason: str,
    *,
    care_event_type: str | None = None,
    evidence: dict | None = None,
    policy_result: dict | None = None,
    attributes: dict | None = None,
) -> None:
    """เปลี่ยนสถานะ = ต้องมี event เสมอ (no silent state change)"""
    from_state = job.state
    job.state = to_state
    await session.flush()
    await audit.emit(
        session,
        _job_scope(scope, job),
        event_type="STATE_TRANSITION",
        subject_type="job",
        subject_id=job.care_job_id,
        job_id=job.care_job_id,
        care_event_type=care_event_type,
        severity=job.severity,
        evidence=evidence,
        policy_result=policy_result,
        transition={"from": from_state, "to": to_state, "reason": reason},
        attributes={"patient_id": job.patient_id, **(attributes or {})},
    )


async def _complete(session: AsyncSession, scope: TenantScope, job: CareJob, reason: str) -> None:
    job.closed_at = now()
    await session.flush()
    await audit.emit(
        session,
        _job_scope(scope, job),
        event_type="JOB_COMPLETED",
        subject_type="job",
        subject_id=job.care_job_id,
        job_id=job.care_job_id,
        severity=job.severity,
        attributes={"patient_id": job.patient_id, "reason": reason, "attempts": job.attempts},
    )


async def _send(
    session: AsyncSession,
    scope: TenantScope,
    job: CareJob,
    *,
    audience: str,
    target_principal_id: str,
    channel: str,
    text: str,
) -> CareNotification:
    notification = CareNotification(
        tenant_id=scope.tenant_id,
        patient_id=job.patient_id,
        audience=audience,
        target_principal_id=target_principal_id,
        channel=channel,
        text=text,
        severity=job.severity,
        care_job_id=job.care_job_id,
        correlation_id=job.correlation_id,
        sent_at=now(),
    )
    session.add(notification)
    await session.flush()
    await _deliver(session, scope, job, notification)
    return notification


async def _deliver(
    session: AsyncSession, scope: TenantScope, job: CareJob, notification: CareNotification
) -> None:
    """ส่งออกช่องทางจริง — ล้มเหลวต้องเห็นได้ ไม่ใช่หายเงียบ"""
    sender = sender_for(notification.channel)
    if sender is None:
        notification.delivery_status = "stored"   # ไม่มีช่องทางจริง เก็บไว้ใน DB อย่างเดียว
        await session.flush()
        return
    try:
        ok, error = await sender(session, notification)
    except Exception as e:  # ช่องทางล่มต้องไม่ทำให้ care loop หยุด
        logger.exception("ส่งข้อความออกช่องทาง %s ไม่สำเร็จ", notification.channel)
        ok, error = False, str(e)

    notification.delivery_status = "sent" if ok else "failed"
    notification.delivery_error = None if ok else (error or "unknown")[:500]
    await session.flush()

    if not ok:
        await audit.emit(
            session,
            _job_scope(scope, job),
            event_type="EXECUTION_FAILED",
            subject_type="execution",
            subject_id=new_id("exec"),
            job_id=job.care_job_id,
            severity=job.severity,
            error=f"ส่งไม่ออกทางช่องทาง {notification.channel}: {notification.delivery_error}",
            attributes={
                "patient_id": job.patient_id,
                "channel": notification.channel,
                "audience": notification.audience,
                "target": notification.target_principal_id,
            },
        )


def _reminder_text(job: CareJob, attempt: int, ask_directly: bool) -> str:
    if ask_directly:
        return f"{job.label} — ทำแล้วหรือยังครับ?"
    if attempt == 1:
        return f"ถึงเวลา {job.label} แล้วนะครับ"
    return f"ขอเตือนอีกครั้งนะครับ — {job.label}"


async def run_due_jobs(session: AsyncSession, scope: TenantScope, *, limit: int = 200) -> dict:
    """tick หนึ่งครั้ง — ส่ง reminder ที่ถึงกำหนด และปิด/ส่งต่องานที่พลาด

    เรียกจาก ARQ worker เป็นระยะ และเรียกตรงได้ในเทส (จึงต้องไม่มี sleep/เวลา implicit)
    """
    pol = escalation_policy.load()
    current = now()
    result = await session.execute(
        scoped(
            select(CareJob)
            .where(
                # รวม acknowledged ด้วย — "รับทราบแล้วแต่ยังไม่ได้ทำ" ต้องถูกตามต่อ
                # (จบที่ตรงนี้ไม่ได้ ไม่งั้นคนที่ตอบว่า "ยัง" จะไม่มีใครเตือนอีกเลย)
                # caregiver ที่กดรับเรื่องจะมี next_attempt_at = None จึงไม่ถูกหยิบมา
                CareJob.state.in_(["pending", "reminded", "acknowledged"]),
                CareJob.next_attempt_at.is_not(None),
                CareJob.next_attempt_at <= current,
            )
            .order_by(CareJob.next_attempt_at)
            .limit(limit),
            CareJob,
            scope,
        )
    )
    jobs = list(result.scalars())

    summary = {"reminded": 0, "missed": 0, "escalated": 0, "deferred": 0}
    for job in jobs:
        patient = await get_patient(session, scope, job.patient_id, required_scope="care.manage")

        if pol.respects_quiet_hours(job.severity) and in_quiet_hours(patient, current):
            job.next_attempt_at = quiet_hours_end(patient, current)
            await session.flush()
            summary["deferred"] += 1
            continue

        if job.attempts >= job.max_attempts:
            await _mark_missed(session, scope, job, pol)
            summary["missed"] += 1
            if job.state == "escalated":
                summary["escalated"] += 1
            continue

        await _remind(session, scope, job, patient, pol)
        summary["reminded"] += 1

    return summary


async def _remind(session: AsyncSession, scope: TenantScope, job: CareJob, patient, pol) -> None:
    capability = SEND_CAPABILITY.get(job.source_kind, "routine.reminder.send")
    decision = evaluate(capability)
    if not decision.may_act_now:
        # agent ส่งเองไม่ได้ → ไม่ส่งเงียบ ๆ แต่บันทึกไว้ว่าถูกกั้นด้วย policy ข้อไหน
        await audit.emit(
            session,
            _job_scope(scope, job),
            event_type="EXECUTION_FAILED",
            subject_type="execution",
            subject_id=new_id("exec"),
            job_id=job.care_job_id,
            policy_result=decision.as_policy_result(),
            error="policy ไม่อนุญาตให้ agent ส่งเอง",
            attributes={"patient_id": job.patient_id, "capability": capability},
        )
        job.next_attempt_at = None
        await session.flush()
        return

    job.attempts += 1
    ask_directly = job.attempts >= pol.ask_directly_on_attempt
    text = _reminder_text(job, job.attempts, ask_directly)
    channel = (patient.channels or ["app"])[0]

    await audit.emit(
        session,
        _job_scope(scope, job),
        event_type="EXECUTION_STARTED",
        subject_type="execution",
        subject_id=new_id("exec"),
        job_id=job.care_job_id,
        policy_result=decision.as_policy_result(),
        attributes={"patient_id": job.patient_id, "attempt": job.attempts, "capability": capability},
    )
    await _send(
        session,
        scope,
        job,
        audience="patient",
        target_principal_id=job.patient_id,
        channel=channel,
        text=text,
    )
    job.next_attempt_at = now() + timedelta(minutes=pol.backoff_for(job.attempts))
    await _transition(
        session,
        scope,
        job,
        "reminded",
        f"ส่ง reminder ครั้งที่ {job.attempts}",
        care_event_type=SENT_EVENT.get(job.source_kind, "care.reminder.sent"),
        policy_result=decision.as_policy_result(),
        attributes={"attempt": job.attempts, "asked_directly": ask_directly, "text": text},
    )


async def _mark_missed(session: AsyncSession, scope: TenantScope, job: CareJob, pol) -> None:
    job.next_attempt_at = None
    await _transition(
        session,
        scope,
        job,
        "missed",
        f"ไม่มีการยืนยันหลังเตือน {job.attempts} ครั้ง",
        care_event_type=MISSED_EVENT.get(job.source_kind, "care.reminder.missed"),
        # 🔒 ไม่มีการยืนยัน = ยังไม่ทำ ห้ามสรุปสาเหตุว่าผู้ป่วย "ลืม"
        evidence={"kind": "none"},
    )
    if pol.notifies_caregiver(job.severity):
        await escalate(session, scope, job)
    else:
        await _complete(session, scope, job, "missed · severity ต่ำ เก็บไว้ใน daily summary")


async def escalate(session: AsyncSession, scope: TenantScope, job: CareJob) -> list[CareNotification]:
    """ส่งต่อให้คน — ผ่าน policy เสมอ และรวมการแจ้งที่ใกล้กันเป็นครั้งเดียว"""
    pol = escalation_policy.load()
    capability = "emergency.escalate" if job.severity == "critical" else "caregiver.notify"
    try:
        decision = evaluate(capability)
        if not decision.may_act_now:
            raise PolicyDenied(decision)
    except PolicyDenied as e:
        await audit.emit(
            session,
            _job_scope(scope, job),
            event_type="EXECUTION_FAILED",
            subject_type="execution",
            subject_id=new_id("exec"),
            job_id=job.care_job_id,
            policy_result=e.decision.as_policy_result(),
            error="policy ไม่อนุญาตให้แจ้ง caregiver อัตโนมัติ",
            attributes={"patient_id": job.patient_id},
        )
        return []

    emergency_only = job.severity == "critical"
    team = await care_team(session, scope, job.patient_id, emergency_only=emergency_only)
    if not team:
        team = await care_team(session, scope, job.patient_id)
    if not team:
        await _transition(
            session,
            scope,
            job,
            "escalated",
            "ไม่มีผู้ดูแลในทีม — บันทึกไว้ให้ตรวจสอบ",
            care_event_type="care.escalated",
            policy_result=decision.as_policy_result(),
            attributes={"targets": []},
        )
        await _complete(session, scope, job, "escalated · ไม่มีผู้รับ")
        return []

    targets = team if pol.notifies_all_targets(job.severity) else team[:1]
    text = f"{job.label}: ยังไม่มีการยืนยันจากผู้ป่วยหลังเตือน {job.attempts} ครั้ง"

    sent: list[CareNotification] = []
    for caregiver in targets:
        existing = await _recent_caregiver_notification(session, scope, job, caregiver.principal_id, pol)
        if existing is not None:
            existing.aggregated_count += 1
            await session.flush()
            await audit.emit(
                session,
                _job_scope(scope, job),
                event_type="TASK_ASSIGNED",
                subject_type="job",
                subject_id=job.care_job_id,
                job_id=job.care_job_id,
                care_event_type="care.escalated",
                severity=job.severity,
                policy_result=decision.as_policy_result(),
                attributes={
                    "patient_id": job.patient_id,
                    "target": caregiver.principal_id,
                    "aggregated_into_notification": existing.id,
                },
            )
            continue
        sent.append(
            await _send(
                session,
                scope,
                job,
                audience="caregiver",
                target_principal_id=caregiver.principal_id,
                channel=caregiver.channel,
                text=text,
            )
        )

    await _transition(
        session,
        scope,
        job,
        "escalated",
        "ส่งต่อให้ผู้ดูแล",
        care_event_type="care.escalated",
        policy_result=decision.as_policy_result(),
        attributes={"targets": [c.principal_id for c in targets], "notified": len(sent)},
    )
    return sent


async def _recent_caregiver_notification(
    session: AsyncSession, scope: TenantScope, job: CareJob, principal_id: str, pol
) -> CareNotification | None:
    window_start = now() - timedelta(minutes=pol.aggregation_window_minutes)
    result = await session.execute(
        scoped(
            select(CareNotification)
            .where(
                CareNotification.patient_id == job.patient_id,
                CareNotification.audience == "caregiver",
                CareNotification.target_principal_id == principal_id,
                CareNotification.severity == job.severity,
                CareNotification.sent_at >= window_start,
            )
            .order_by(CareNotification.sent_at.desc()),
            CareNotification,
            scope,
        )
    )
    return result.scalars().first()


async def get_job(session: AsyncSession, scope: TenantScope, care_job_id: str) -> CareJob:
    job = await session.get(CareJob, care_job_id)
    if job is None:
        raise JobNotFound(f"ไม่พบ care job {care_job_id}")
    assert_same_tenant(scope, job)
    return job


async def acknowledge(
    session: AsyncSession,
    scope: TenantScope,
    care_job_id: str,
    *,
    evidence_kind: str = "patient_confirmed",
    done: bool = True,
) -> CareJob:
    """ผู้ป่วยยืนยันว่าทำแล้ว — ต้องมี evidence เสมอ ห้ามอนุมานเอง"""
    job = await get_job(session, scope, care_job_id)
    if job.state in ("confirmed", "cancelled"):
        return job

    evidence = {"kind": evidence_kind, "recorded_by": scope.principal.as_dict()}
    job.evidence = evidence
    job.next_attempt_at = None
    if not done:
        await _transition(
            session, scope, job, "acknowledged", "ผู้ป่วยรับทราบแต่ยังไม่ได้ทำ", evidence=evidence
        )
        job.next_attempt_at = now() + timedelta(minutes=escalation_policy.load().backoff_for(job.attempts))
        await session.flush()
        return job

    await _transition(
        session,
        scope,
        job,
        "confirmed",
        "ผู้ป่วยยืนยันว่าทำแล้ว",
        care_event_type=CONFIRMED_EVENT.get(job.source_kind, "care.reminder.acknowledged"),
        evidence=evidence,
    )
    await _complete(session, scope, job, "confirmed")
    return job


async def caregiver_acknowledge(session: AsyncSession, scope: TenantScope, care_job_id: str) -> CareJob:
    """ผู้ดูแลรับเรื่องแล้ว — หยุดเตือนทันที (escalation_rules)"""
    job = await get_job(session, scope, care_job_id)
    job.next_attempt_at = None
    await _transition(
        session,
        scope,
        job,
        "acknowledged",
        "ผู้ดูแลรับเรื่องแล้ว",
        evidence={"kind": "caregiver_confirmed", "recorded_by": scope.principal.as_dict()},
    )
    await _complete(session, scope, job, "caregiver acknowledged")
    return job


async def jobs_for_source(
    session: AsyncSession,
    scope: TenantScope,
    *,
    source_kind: str,
    source_id: str,
    due_at: datetime | None = None,
) -> list[CareJob]:
    """หา care job ที่ addon อื่นสร้างไว้จากของของตัวเอง

    มีไว้เพื่อให้ addon โดเมนไม่ต้อง `import ... models import CareJob` ข้าม addon
    (กติกาใน architecture/team-plan.md — คุยกันผ่าน service function เท่านั้น)
    """
    stmt = select(CareJob).where(
        CareJob.source_kind == source_kind, CareJob.source_id == source_id
    )
    if due_at is not None:
        stmt = stmt.where(CareJob.due_at == due_at)
    result = await session.execute(scoped(stmt.order_by(CareJob.due_at), CareJob, scope))
    return list(result.scalars())


async def open_jobs(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, states: list[str] | None = None
) -> list[CareJob]:
    stmt = select(CareJob).where(CareJob.patient_id == patient_id)
    if states:
        stmt = stmt.where(CareJob.state.in_(states))
    result = await session.execute(scoped(stmt.order_by(CareJob.due_at), CareJob, scope))
    return list(result.scalars())
