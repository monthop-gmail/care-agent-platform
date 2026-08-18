from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from core.auth import require_permission
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from care_addons.ap_tenancy.deps import ScopeDep, SessionDep
from care_addons.care_routine import services as svc

router = APIRouter(prefix="/api/care/routines", tags=["care: routine"])


class RoutineIn(BaseModel):
    patient_id: str
    kind: str
    label: str
    scheduled_time: str
    recurrence_type: str = "daily"
    days_of_week: list[int] | None = None
    grace_minutes: int = 30
    severity: str = "medium"


@router.post("", status_code=201)
async def add_routine(
    body: RoutineIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.routine.manage"))],
) -> dict:
    try:
        item = await svc.add_routine(
            session,
            scope,
            patient_id=body.patient_id,
            kind=body.kind,
            label=body.label,
            scheduled_time=body.scheduled_time,
            recurrence_type=body.recurrence_type,
            days_of_week=body.days_of_week,
            grace_minutes=body.grace_minutes,
            severity=body.severity,
        )
    except svc.FeatureDisabled as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await session.commit()
    return {"routine_id": item.routine_id, "label": item.label, "scheduled_time": item.scheduled_time}


@router.get("")
async def list_routines(patient_id: str, scope: ScopeDep, session: SessionDep) -> list[dict]:
    items = await svc.list_routines(session, scope, patient_id)
    return [
        {
            "routine_id": i.routine_id,
            "kind": i.kind,
            "label": i.label,
            "scheduled_time": i.scheduled_time,
            "severity": i.severity,
        }
        for i in items
    ]


@router.post("/materialize")
async def materialize(
    patient_id: str, scope: ScopeDep, session: SessionDep, for_date: date | None = None
) -> dict:
    """สร้าง care job ของวันนั้น — เรียกซ้ำได้ ไม่สร้างซ้ำ"""
    jobs = await svc.materialize_day(session, scope, patient_id, for_date=for_date)
    await session.commit()
    return {"created": len(jobs), "care_job_ids": [j.care_job_id for j in jobs]}


@router.get("/today")
async def today(patient_id: str, scope: ScopeDep, session: SessionDep) -> list[dict]:
    """แผนวันนี้แบบที่ผู้ป่วยเห็น"""
    return await svc.today_plan(session, scope, patient_id)
