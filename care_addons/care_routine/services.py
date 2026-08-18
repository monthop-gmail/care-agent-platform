"""กิจวัตร → care job

หลักการ: routine ไม่ส่งข้อความเอง — มันสร้าง job แล้วให้ engine ของ care_escalation เดินวงจร
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_tenancy.clock import now
from care_addons.ap_tenancy.ids import new_id
from care_addons.ap_tenancy.services import TenantScope, scoped
from care_addons.care_escalation.models import CareJob
from care_addons.care_escalation.services import create_job
from care_addons.care_patient.services import feature_enabled, get_patient
from care_addons.care_routine.models import KINDS, CareRoutineItem

# routine kind ไหนนับเป็นงานชนิดใดในสายตาของ engine (มีผลต่อชื่อ event และ capability)
SOURCE_KIND = {"meal": "meal", "medication": "medication"}


class FeatureDisabled(PermissionError):
    """ความสามารถนี้ยังไม่ได้เปิดใน care profile ของผู้ป่วย — ไม่ใช่ error ของระบบ"""


async def add_routine(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    kind: str,
    label: str,
    scheduled_time: str,
    recurrence_type: str = "daily",
    days_of_week: list[int] | None = None,
    grace_minutes: int = 30,
    severity: str = "medium",
) -> CareRoutineItem:
    if kind not in KINDS:
        raise ValueError(f"routine kind ไม่รู้จัก: {kind} — เพิ่มใน contract ก่อน")
    patient = await get_patient(session, scope, patient_id, required_scope="care.manage")
    if not feature_enabled(patient, "routine"):
        raise FeatureDisabled("care_profile.routine ยังปิดอยู่สำหรับผู้ป่วยรายนี้")

    item = CareRoutineItem(
        routine_id=new_id("rtn"),
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        kind=kind,
        label=label,
        scheduled_time=scheduled_time,
        recurrence_type=recurrence_type,
        days_of_week=days_of_week,
        grace_minutes=grace_minutes,
        severity=severity,
    )
    session.add(item)
    await session.flush()
    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=item.routine_id,
        transition={"from": None, "to": "enabled", "reason": "routine created"},
        attributes={
            "record_type": "routine_item",
            "patient_id": patient_id,
            "kind": kind,
            "scheduled_time": scheduled_time,
        },
    )
    return item


async def list_routines(
    session: AsyncSession, scope: TenantScope, patient_id: str
) -> list[CareRoutineItem]:
    result = await session.execute(
        scoped(
            select(CareRoutineItem)
            .where(CareRoutineItem.patient_id == patient_id, CareRoutineItem.enabled.is_(True))
            .order_by(CareRoutineItem.scheduled_time),
            CareRoutineItem,
            scope,
        )
    )
    return list(result.scalars())


def _occurs_on(item: CareRoutineItem, day: date) -> bool:
    if item.recurrence_type == "daily":
        return True
    if item.recurrence_type in ("weekly", "specific_days"):
        return day.weekday() in (item.days_of_week or [])
    return False


def _due_at_utc(item: CareRoutineItem, day: date, tz: ZoneInfo) -> datetime:
    hour, _, minute = item.scheduled_time.partition(":")
    local = datetime.combine(day, time(int(hour), int(minute)), tzinfo=tz)
    return local.astimezone(ZoneInfo("UTC"))


async def materialize_day(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, for_date: date | None = None
) -> list[CareJob]:
    """สร้าง care job ของวันนั้นให้ครบ — เรียกซ้ำได้ ไม่สร้างซ้ำ (idempotent)"""
    patient = await get_patient(session, scope, patient_id, required_scope="care.manage")
    tz = ZoneInfo(patient.timezone or "Asia/Bangkok")
    day = for_date or now().astimezone(tz).date()

    created: list[CareJob] = []
    for item in await list_routines(session, scope, patient_id):
        if not _occurs_on(item, day):
            continue
        due_at = _due_at_utc(item, day, tz)
        existing = await session.execute(
            scoped(
                select(CareJob).where(
                    CareJob.source_kind == SOURCE_KIND.get(item.kind, "routine"),
                    CareJob.source_id == item.routine_id,
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
                source_kind=SOURCE_KIND.get(item.kind, "routine"),
                source_id=item.routine_id,
                label=item.label,
                due_at=due_at,
                severity=item.severity,
            )
        )
    return created


async def today_plan(session: AsyncSession, scope: TenantScope, patient_id: str) -> list[dict]:
    """แผนวันนี้แบบที่ผู้ป่วยเห็น — สถานะมาจาก job จริง ไม่ใช่การเดา"""
    return await plan_for_date(session, scope, patient_id)


async def plan_for_date(
    session: AsyncSession, scope: TenantScope, patient_id: str, day: date | None = None
) -> list[dict]:
    """แผนของวันที่ระบุ — ใช้ตอบคำถามแบบ "พรุ่งนี้ต้องทำอะไร" โดยไม่ต้องเดา"""
    patient = await get_patient(session, scope, patient_id)
    tz = ZoneInfo(patient.timezone or "Asia/Bangkok")
    today = day or now().astimezone(tz).date()
    start = datetime.combine(today, time(0, 0), tzinfo=tz).astimezone(ZoneInfo("UTC"))
    end = start + timedelta(days=1)

    result = await session.execute(
        scoped(
            select(CareJob)
            .where(CareJob.patient_id == patient_id, CareJob.due_at >= start, CareJob.due_at < end)
            .order_by(CareJob.due_at),
            CareJob,
            scope,
        )
    )
    plan = []
    for job in result.scalars():
        plan.append(
            {
                "time": job.due_at.astimezone(tz).strftime("%H:%M"),
                "label": job.label,
                "kind": job.source_kind,
                "state": job.state,
                # 🔒 ยังไม่ยืนยัน = ยังไม่มีข้อมูล ไม่ใช่ "ยังไม่ได้ทำ"
                "confirmed": job.state == "confirmed",
                "care_job_id": job.care_job_id,
            }
        )
    return plan
