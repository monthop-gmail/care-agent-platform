"""สรุปประจำวันให้ผู้ดูแล — และรอบวันของทั้งระบบ

🔒 ADR-0004 ข้อ 4: รายงาน **ข้อเท็จจริงที่วัดได้** เท่านั้น
   "กินยาเช้าแล้ว · มื้อเที่ยงยังไม่ยืนยัน 2 ครั้ง" ได้
   "วันนี้ดูสับสนกว่าปกติ" **ไม่ได้** — นั่นคือการตีความอาการ ซึ่งเป็นงานของหมอ
   ทุกบรรทัดในข้อความมาจากสถานะของ care_job ที่มี event รองรับ ไม่มีบรรทัดไหนมาจากการเดา

🔒 ไม่มีตัวเลขไหนในสรุปที่ "อนุมาน" ว่าทำแล้ว — ไม่ยืนยัน = ไม่ยืนยัน ไม่ใช่ทำแล้ว (ADR-0004)
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_approval import services as approvals
from care_addons.ap_audit import services as audit
from care_addons.ap_tenancy.clock import now
from care_addons.ap_tenancy.ids import new_id
from care_addons.ap_tenancy.services import TenantScope, scoped
from care_addons.care_escalation import services as escalation
from care_addons.care_escalation.models import CareJob
from care_addons.care_orchestrator import summary_policy
from care_addons.care_orchestrator.models import CareDailySummary
from care_addons.care_patient.models import CarePatient
from care_addons.care_patient.services import feature_enabled

# source_kind ของงาน → หัวข้อในสรุป (ตาม daily_summary.include ของ escalation-policy)
BUCKETS = {
    "meal": "meals",
    "medication": "medication",
    "appointment": "appointments",
    "safety": "safety",
}
DEFAULT_BUCKET = "activities"

BUCKET_LABEL = {
    "meals": "มื้ออาหาร",
    "medication": "ยา",
    "activities": "กิจวัตร",
    "appointments": "นัดหมอ",
    "safety": "ความปลอดภัย",
}

DONE_STATES = ("confirmed",)
MISSED_STATES = ("missed", "escalated")


def _tz(patient: CarePatient) -> ZoneInfo:
    try:
        return ZoneInfo(patient.timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def local_date_of(patient: CarePatient, moment: datetime) -> date:
    return moment.astimezone(_tz(patient)).date()


def _day_bounds(patient: CarePatient, local_day: date) -> tuple[datetime, datetime]:
    """ขอบเขตของ "วันนั้นตามเวลาผู้ป่วย" แปลงเป็น UTC — due_at เก็บเป็น UTC เสมอ"""
    tz = _tz(patient)
    start = datetime.combine(local_day, time(0, 0), tzinfo=tz)
    return start, start + timedelta(days=1)


async def build_facts(
    session: AsyncSession, scope: TenantScope, patient: CarePatient, local_day: date
) -> dict:
    """นับจากสถานะของงานจริงในวันนั้น — ไม่มีการตีความใด ๆ ที่นี่"""
    start, end = _day_bounds(patient, local_day)
    result = await session.execute(
        scoped(
            select(CareJob)
            .where(
                CareJob.patient_id == patient.patient_id,
                CareJob.due_at >= start,
                CareJob.due_at < end,
            )
            .order_by(CareJob.due_at),
            CareJob,
            scope,
        )
    )
    jobs = list(result.scalars())

    buckets: dict[str, dict] = {}
    for job in jobs:
        bucket = buckets.setdefault(
            BUCKETS.get(job.source_kind, DEFAULT_BUCKET),
            {"done": 0, "missed": 0, "open": 0, "items": []},
        )
        if job.state in DONE_STATES:
            outcome = "done"
        elif job.state in MISSED_STATES:
            outcome = "missed"
        else:
            outcome = "open"
        bucket[outcome] += 1
        bucket["items"].append(
            {
                "label": job.label,
                "state": job.state,
                "due_local": job.due_at.astimezone(_tz(patient)).strftime("%H:%M"),
                "attempts": job.attempts,
            }
        )

    # งานค้าง = ถึงกำหนดแล้วแต่ยังไม่ปิด ไม่ว่าจะของวันไหน — คนดูแลต้องเห็นของที่ค้างข้ามวันด้วย
    stalled = [
        {
            "label": j.label,
            "state": j.state,
            "due_at": j.due_at.isoformat(),
            "attempts": j.attempts,
        }
        for j in await escalation.open_jobs(
            session, scope, patient.patient_id, states=["pending", "reminded", "acknowledged", "escalated"]
        )
        if j.due_at <= now() and j.closed_at is None
    ]

    waiting = [
        {
            "request_id": r.request_id,
            "capability": r.capability,
            "summary": r.summary,
            "requested_at": r.requested_at.isoformat(),
        }
        for r in await approvals.pending_requests(session, scope)
    ]

    return {
        "local_date": local_day.isoformat(),
        "timezone": patient.timezone,
        "buckets": buckets,
        "stalled_tasks": stalled,
        "awaiting_decision": waiting,
        "counted_jobs": len(jobs),
    }


def render(patient: CarePatient, facts: dict) -> str:
    """ข้อความที่ผู้ดูแลจะได้อ่าน — ประโยคบอกเล่าล้วน ๆ ไม่มีคำวินิจฉัย ไม่มีคำแนะนำทางการแพทย์"""
    lines = [f"สรุปวันที่ {facts['local_date']} ของ{patient.display_name}"]

    buckets = facts.get("buckets") or {}
    for key in ("meals", "medication", "activities", "appointments", "safety"):
        bucket = buckets.get(key)
        if not bucket:
            continue
        parts = []
        if bucket["done"]:
            parts.append(f"ยืนยันแล้ว {bucket['done']}")
        if bucket["missed"]:
            parts.append(f"ไม่ได้ยืนยัน {bucket['missed']}")
        if bucket["open"]:
            parts.append(f"ยังไม่ถึงกำหนด/รออยู่ {bucket['open']}")
        lines.append(f"· {BUCKET_LABEL[key]}: {' · '.join(parts)}")

    stalled = facts.get("stalled_tasks") or []
    if stalled:
        lines.append(f"· ค้างอยู่ {len(stalled)} รายการ: " + ", ".join(s["label"] for s in stalled[:5]))

    waiting = facts.get("awaiting_decision") or []
    if waiting:
        lines.append(f"· รอคุณตัดสิน {len(waiting)} เรื่อง: " + ", ".join(w["summary"] for w in waiting[:3]))

    if len(lines) == 1:
        lines.append("· วันนี้ไม่มีงานที่ตั้งไว้")

    # 🔒 บอกให้ชัดว่านี่คือ "สิ่งที่ระบบเห็น" ไม่ใช่ "สิ่งที่เกิดขึ้นจริงทั้งหมด"
    # ไม่ยืนยัน ≠ ไม่ได้ทำ — ผู้ดูแลต้องไม่เข้าใจผิดว่าตัวเลขนี้คือความจริงทั้งหมดของวัน
    lines.append("(นับจากการยืนยันที่บันทึกไว้เท่านั้น — ไม่ได้ยืนยันไม่ได้แปลว่าไม่ได้ทำ)")
    return "\n".join(lines)


async def existing_summary(
    session: AsyncSession, scope: TenantScope, patient_id: str, local_day: date
) -> CareDailySummary | None:
    result = await session.execute(
        scoped(
            select(CareDailySummary).where(
                CareDailySummary.patient_id == patient_id,
                CareDailySummary.local_date == local_day,
            ),
            CareDailySummary,
            scope,
        )
    )
    return result.scalars().first()


async def send_daily_summary(
    session: AsyncSession,
    scope: TenantScope,
    patient: CarePatient,
    *,
    local_day: date | None = None,
    force: bool = False,
) -> CareDailySummary | None:
    """สร้างและส่งสรุปของวันนั้น — เรียกซ้ำได้ ส่งจริงครั้งเดียว

    คืน None เมื่อวันนั้นส่งไปแล้ว (ไม่ใช่ error — worker เรียกซ้ำทุกรอบโดยตั้งใจ)
    """
    day = local_day or local_date_of(patient, now())
    if not force:
        already = await existing_summary(session, scope, patient.patient_id, day)
        if already is not None:
            return None

    facts = await build_facts(session, scope, patient, day)
    text = render(patient, facts)

    row = CareDailySummary(
        summary_id=new_id("sum"),
        tenant_id=scope.tenant_id,
        patient_id=patient.patient_id,
        local_date=day,
        facts=facts,
        text=text,
        generated_at=now(),
    )
    try:
        # savepoint — ถ้าชนกับ worker อื่นที่ชิงสร้างไปก่อน ต้องเสียแค่แถวนี้
        # ไม่ใช่ทั้ง transaction ที่มีสรุปของผู้ป่วยคนอื่นใน tenant เดียวกันอยู่ด้วย
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        return None

    sent = await escalation.send_to_caregivers(
        session,
        scope,
        patient_id=patient.patient_id,
        text=text,
        capability="caregiver.notify",
        severity="low",
        all_targets=True,
    )
    row.sent_at = now() if sent else None
    row.recipients = len(sent)
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="JOB_COMPLETED",
        subject_type="record",
        subject_id=row.summary_id,
        care_event_type="care.summary.sent",
        severity="low",
        attributes={
            "record_type": "daily_summary",
            "patient_id": patient.patient_id,
            "local_date": day.isoformat(),
            "recipients": row.recipients,
            "counted_jobs": facts["counted_jobs"],
            "stalled": len(facts["stalled_tasks"]),
        },
    )
    return row


async def due_for_summary(session: AsyncSession, scope: TenantScope) -> list[CarePatient]:
    """ผู้ป่วยที่ถึงเวลาสรุปของ **วันนี้ตามเวลาของเขาเอง** แล้ว และยังไม่ได้ส่ง

    เวลาส่งเป็นเวลาท้องถิ่นของผู้ป่วย ไม่ใช่ของ server — ครอบครัวที่อยู่คนละ timezone
    ต้องได้สรุปตอนสองทุ่มของบ้านผู้ป่วย ไม่ใช่ตอนสองทุ่มของ data center
    """
    send_at = summary_policy.send_at()
    moment = now()
    result = await session.execute(scoped(select(CarePatient), CarePatient, scope))
    due: list[CarePatient] = []
    for patient in result.scalars():
        if not feature_enabled(patient, "caregiver_escalation"):
            continue
        local = moment.astimezone(_tz(patient))
        if local.time() < send_at:
            continue
        if await existing_summary(session, scope, patient.patient_id, local.date()) is not None:
            continue
        due.append(patient)
    return due


async def run_daily_summaries(session: AsyncSession, scope: TenantScope) -> dict:
    """รอบวัน — ส่งสรุปให้ทุกคนที่ถึงเวลา แล้วปิดคำขออนุมัติที่เลยกำหนด

    🔒 การหมดอายุของคำขอทำให้ระบบ **หยุด** ไม่ใช่ลงมือ — ดู ap_approval.expire_overdue
    """
    summaries = 0
    for patient in await due_for_summary(session, scope):
        if await send_daily_summary(session, scope, patient) is not None:
            summaries += 1
    expired = await approvals.expire_overdue(session, scope)
    return {"summaries": summaries, "expired_approvals": expired}
