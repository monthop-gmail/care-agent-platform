from __future__ import annotations

from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep
from core.auth import require_permission
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from care_addons.care_activity import services as svc

router = APIRouter(prefix="/api/care/activities", tags=["care: activity"])


class ActivityIn(BaseModel):
    patient_id: str
    activity_type: str
    label: str = ""
    steps: list[dict] | None = None
    context_checks: list[str] | None = None


class SignalIn(BaseModel):
    event: str = Field(min_length=1)
    source_system: str = Field(min_length=1)


@router.post("", status_code=201)
async def start(
    body: ActivityIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.activity.manage"))],
) -> dict:
    try:
        activity = await svc.start_activity(
            session,
            scope,
            patient_id=body.patient_id,
            activity_type=body.activity_type,
            label=body.label,
            steps=body.steps,
            context_checks=body.context_checks,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return await svc.as_activity(session, scope, activity)


@router.get("")
async def list_open(
    patient_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.activity.read"))],
) -> list[dict]:
    return [
        await svc.as_activity(session, scope, activity)
        for activity in await svc.open_activities(session, scope, patient_id)
    ]


@router.post("/steps/{step_id}/complete")
async def complete_step(
    step_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.activity.manage"))],
) -> dict:
    try:
        step = await svc.complete_step(session, scope, step_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    activity = await svc.get_activity(session, scope, step.activity_id)
    return await svc.as_activity(session, scope, activity)


@router.post("/{activity_id}/signal")
async def signal(
    activity_id: str,
    body: SignalIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.activity.manage"))],
) -> dict:
    """อุปกรณ์แจ้งว่าทำงานเสร็จ — 🔒 งานยังไม่จบจนกว่าคนจะทำขั้นถัดไป"""
    try:
        await svc.external_signal(
            session, scope, activity_id=activity_id, event=body.event,
            source_system=body.source_system,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    activity = await svc.get_activity(session, scope, activity_id)
    return await svc.as_activity(session, scope, activity)
