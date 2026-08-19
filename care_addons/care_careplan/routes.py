from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep
from core.auth import require_permission
from core.tenancy import Principal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from care_addons.care_careplan import services as svc

router = APIRouter(prefix="/api/care/careplan", tags=["care: careplan"])


def principal_of(user: Any) -> Principal:
    return Principal(
        type="human",
        id=f"user-{user.id}",
        display_name=getattr(user, "full_name", "") or getattr(user, "email", ""),
    )


class TaskIn(BaseModel):
    patient_id: str
    task_type: str
    description: str = Field(min_length=1)
    frequency: dict
    source: dict
    scheduled_times: list[str] | None = None
    duration_minutes: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    severity: str = "medium"
    source_document: str | None = None


class StatusIn(BaseModel):
    status: str
    reason: str = Field(min_length=1)


def _out(task: Any) -> dict:
    return {
        **svc.as_careplan_task(task),
        "scheduled_times": task.scheduled_times,
        "activated_by": task.activated_by,
        "reminders_enabled": task.reminders_enabled,
    }


@router.post("", status_code=201)
async def propose(
    body: TaskIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.careplan.manage"))],
) -> dict:
    """จดคำสั่งหลังพบหมอ — ได้แค่ proposed แล้วเข้าคิวรอคนยืนยันเสมอ"""
    try:
        task = await svc.propose_task(
            session,
            scope,
            patient_id=body.patient_id,
            task_type=body.task_type,
            description=body.description,
            frequency=body.frequency,
            source=body.source,
            scheduled_times=body.scheduled_times,
            duration_minutes=body.duration_minutes,
            start_date=body.start_date,
            end_date=body.end_date,
            severity=body.severity,
            source_document=body.source_document,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return _out(task)


@router.get("")
async def list_tasks(
    patient_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.careplan.read"))],
    status: str | None = None,
) -> list[dict]:
    tasks = await svc.list_tasks(
        session, scope, patient_id, statuses=[status] if status else None
    )
    return [_out(task) for task in tasks]


@router.post("/{task_id}/activate")
async def activate(
    task_id: str,
    scope: ScopeDep,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("care.careplan.manage"))],
) -> dict:
    """ผู้ดูแลที่อยู่ตรงนั้นยืนยันได้เลย — คำขอที่ค้างในคิวจะถูกถอน ไม่ใช่ถูกอนุมัติ"""
    try:
        task = await svc.activate_task(
            session, scope, task_id, activated_by=principal_of(user)
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (svc.CarePlanRuleViolation, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return _out(task)


@router.post("/{task_id}/status")
async def set_status(
    task_id: str,
    body: StatusIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.careplan.manage"))],
) -> dict:
    try:
        task = await svc.set_status(session, scope, task_id, status=body.status, reason=body.reason)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (svc.CarePlanRuleViolation, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return _out(task)


@router.get("/{task_id}/adherence")
async def adherence(
    task_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.careplan.read"))],
    days: int = 7,
) -> dict:
    """ทำตามคำสั่งได้แค่ไหน — ไม่มีบันทึกจะตอบว่าข้อมูลไม่พอ ไม่ใช่ 0%"""
    try:
        return await svc.adherence(session, scope, task_id, days=days)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
