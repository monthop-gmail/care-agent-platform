"""สรุปประจำวันให้ผู้ดูแล — และรอบวันของทั้งระบบ

🔒 ADR-0004 ข้อ 4: รายงาน **ข้อเท็จจริงที่วัดได้** เท่านั้น
   "กินยาเช้าแล้ว · มื้อเที่ยงยังไม่ยืนยัน 2 ครั้ง" ได้
   "วันนี้ดูสับสนกว่าปกติ" **ไม่ได้** — นั่นคือการตีความอาการ ซึ่งเป็นงานของหมอ
   ทุกบรรทัดในข้อความมาจากสถานะของ care_job ที่มี event รองรับ ไม่มีบรรทัดไหนมาจากการเดา

🔒 ไม่มีตัวเลขไหนในสรุปที่ "อนุมาน" ว่าทำแล้ว — ไม่ยืนยัน = ไม่ยืนยัน ไม่ใช่ทำแล้ว (ADR-0004)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.clock import now
from core.tenancy import TenantScope, new_id, scoped
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_approval import services as approvals
from care_addons.ap_audit import services as audit
from care_addons.care_escalation import services as escalation
from care_addons.care_escalation.models import CareJob
from care_addons.care_orchestrator import summary_policy
from care_addons.care_orchestrator.models import CareDailySummary
from care_addons.care_patient.models import CarePatient
from care_addons.care_patient.services import feature_enabled

logger = logging.getLogger(__name__)

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


def _utc(value: datetime) -> datetime:
    """เวลาที่อ่านกลับมาจาก DB อาจไม่มี timezone ติดมา (sqlite เก็บ naive)

    ระบบเก็บทุกอย่างเป็น UTC อยู่แล้ว — ที่นี่แค่ติดป้ายให้ตรงกับความจริง
    ไม่ใช่การแปลงเขตเวลา · ถ้าไม่ทำ `astimezone()` จะตีความว่าเป็นเวลาท้องถิ่นของ server เงียบ ๆ
    """
    return value if value.tzinfo else value.replace(tzinfo=ZoneInfo("UTC"))


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
                "due_local": _utc(job.due_at).astimezone(_tz(patient)).strftime("%H:%M"),
                "attempts": job.attempts,
            }
        )

    # งานค้าง = ถึงกำหนดแล้วแต่ยังไม่ปิด ไม่ว่าจะของวันไหน — คนดูแลต้องเห็นของที่ค้างข้ามวันด้วย
    stalled = [
        {
            "label": j.label,
            "state": j.state,
            "due_at": _utc(j.due_at).isoformat(),
            "attempts": j.attempts,
        }
        for j in await escalation.open_jobs(
            session, scope, patient.patient_id, states=["pending", "reminded", "acknowledged", "escalated"]
        )
        if _utc(j.due_at) <= now() and j.closed_at is None
    ]

    from care_addons.care_safety import services as safety

    # 🔒 รายงานเฉพาะ "สัญญาณที่ได้รับ" — ไม่มีบรรทัดไหนบอกว่า "ที่เหลือปลอดภัย"
    #    อุปกรณ์ที่เงียบเพราะแบตหมดกับบ้านที่ปลอดภัยจริง หน้าตาเหมือนกันในข้อมูลของเรา
    signals = [
        {
            "kind": e.kind,
            "severity": e.severity,
            "state": e.state,
            "observed_at": _utc(e.observed_at).isoformat(),
            "repeat_count": e.repeat_count,
            "source": (e.source or {}).get("system"),
        }
        for e in await safety.open_events(session, scope, patient.patient_id)
    ]

    # สิทธิ์ของคนนอกครอบครัวที่ยังเปิดอยู่ — 🔒 เงื่อนไขที่ไม่เป็นจริงแล้วต้องเห็นได้
    #    ไม่งั้นใบยินยอมที่ตายแล้วจะค้างอยู่ในระบบโดยไม่มีใครไปเก็บกวาด (ADR-0010)
    from care_addons.care_organization import services as organizations

    clinical_access = [
        row
        for row in await organizations.open_access(session, scope, patient.patient_id)
        if row["organization_id"]
    ]

    waiting = [
        {
            "request_id": r.request_id,
            "capability": r.capability,
            "summary": r.summary,
            "requested_at": _utc(r.requested_at).isoformat(),
        }
        for r in await approvals.pending_requests(session, scope)
    ]

    return {
        "local_date": local_day.isoformat(),
        "timezone": patient.timezone,
        "buckets": buckets,
        "stalled_tasks": stalled,
        "safety_signals": signals,
        "clinical_access": clinical_access,
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

    signals = facts.get("safety_signals") or []
    if signals:
        kinds = ", ".join(sorted({s["kind"] for s in signals}))
        lines.append(f"· สัญญาณความปลอดภัยที่ยังไม่ปิด {len(signals)} รายการ: {kinds}")

    access = facts.get("clinical_access") or []
    stale = [a for a in access if not a["conditions_hold"]]
    if access:
        line = f"· ผู้ให้การรักษาที่เข้าถึงข้อมูลได้ {len(access) - len(stale)} ราย"
        if stale:
            line += f" · มี {len(stale)} ใบที่เงื่อนไขไม่เป็นจริงแล้ว (ควรเพิกถอน)"
        lines.append(line)

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

    `force=True` = **คำนวณใบของวันนั้นใหม่** จากข้อมูลล่าสุดแล้วอัปเดตใบเดิม
    ไม่ใช่การส่งซ้ำ — หนึ่งวันยังได้ข้อความเดียวเสมอ (unique constraint ระดับ DB ก็บังคับไว้)
    """
    day = local_day or local_date_of(patient, now())
    already = await existing_summary(session, scope, patient.patient_id, day)
    if already is not None:
        if not force:
            return None
        already.facts = await build_facts(session, scope, patient, day)
        already.text = render(patient, already.facts)
        already.generated_at = now()
        await session.flush()
        return already

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


async def materialize_today(session: AsyncSession, scope: TenantScope) -> dict:
    """สร้างงานของ "วันนี้" ให้ผู้ป่วยทุกคนใน tenant — เรียกซ้ำได้ ไม่สร้างซ้ำ

    ก่อนมีขั้นนี้ งานประจำวันเกิดขึ้นก็ต่อเมื่อมีคนยิง `POST /api/care/routines/materialize`
    ซึ่งแปลว่า closed loop ทั้งวงขึ้นอยู่กับว่ามีใครจำได้ไหม — ไม่ใช่คุณสมบัติที่ยอมรับได้
    ของระบบที่ผู้ป่วยพึ่งพาเรื่องยา

    🔒 ผู้ป่วยที่ยังไม่ได้ให้ consent กับ principal ของ orchestrator จะถูก **ข้าม**
       ไม่ใช่ทำให้ทั้ง tenant หยุด — ไม่มี consent = ไม่แตะข้อมูลของคนนั้น (ADR-0007)
    """
    from care_addons.ap_consent.services import ConsentDenied
    from care_addons.care_careplan import services as careplan
    from care_addons.care_routine import services as routines

    counts = {"routine_jobs": 0, "careplan_jobs": 0, "skipped_no_consent": 0}
    result = await session.execute(scoped(select(CarePatient), CarePatient, scope))
    for patient in result.scalars():
        try:
            counts["routine_jobs"] += len(
                await routines.materialize_day(session, scope, patient.patient_id)
            )
            counts["careplan_jobs"] += len(
                await careplan.materialize_day(session, scope, patient.patient_id)
            )
        except ConsentDenied:
            counts["skipped_no_consent"] += 1
            logger.warning(
                "orchestrator ยังไม่มี consent สำหรับผู้ป่วย %s — ข้ามการสร้างงานของวันนี้",
                patient.patient_id,
            )
    return counts


async def run_cycle(session: AsyncSession, scope: TenantScope) -> dict:
    """รอบเดียวของ orchestrator

    สร้างงานของวัน → หางานหลายขั้นตอนที่ค้าง → ส่งสรุปที่ถึงเวลา → ปิดคำขอที่เลยกำหนด
    """
    from care_addons.care_activity import services as activities

    result = await materialize_today(session, scope)
    result["stalled_steps"] = await activities.sweep_stalled(session, scope)
    result.update(await run_daily_summaries(session, scope))
    return result


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
