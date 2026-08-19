from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep
from core.auth import require_permission
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from care_addons.care_appointment import services as svc

router = APIRouter(prefix="/api/care/appointments", tags=["care: appointment"])


class AppointmentIn(BaseModel):
    patient_id: str
    starts_at: datetime
    doctor_name: str = ""
    specialty: str | None = None
    facility: str = ""
    purpose: str = ""
    reminder_offsets_hours: list[int] | None = None


class StepIn(BaseModel):
    kind: str
    label: str
    due_at: datetime
    order: int = 0
    source_document: str | None = None


def _serialize(a) -> dict:
    return {
        "appointment_id": a.appointment_id,
        "patient_id": a.patient_id,
        "starts_at": a.starts_at,
        "doctor_name": a.doctor_name,
        "specialty": a.specialty,
        "facility": a.facility,
        "purpose": a.purpose,
        "status": a.status,
    }


@router.post("", status_code=201)
async def create(
    body: AppointmentIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.appointment.manage"))],
) -> dict:
    try:
        appointment = await svc.create_appointment(
            session,
            scope,
            patient_id=body.patient_id,
            starts_at=body.starts_at,
            doctor_name=body.doctor_name,
            specialty=body.specialty,
            facility=body.facility,
            purpose=body.purpose,
            reminder_offsets_hours=body.reminder_offsets_hours,
        )
    except (ValueError, svc.PreparationRuleViolation) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await svc.schedule_reminders(session, scope, appointment.appointment_id)
    await session.commit()
    return _serialize(appointment)


@router.get("")
async def list_upcoming(patient_id: str, scope: ScopeDep, session: SessionDep) -> list[dict]:
    return [_serialize(a) for a in await svc.upcoming(session, scope, patient_id)]


@router.post("/{appointment_id}/preparation/default", status_code=201)
async def build_plan(appointment_id: str, scope: ScopeDep, session: SessionDep) -> dict:
    """สร้างแผนเตรียมตัวมาตรฐาน — ไม่รวมข้อกำหนดทางการแพทย์ (ต้องเพิ่มเองพร้อมเอกสาร)"""
    try:
        steps = await svc.build_default_plan(session, scope, appointment_id)
        created = await svc.start_preparation(session, scope, appointment_id)
    except svc.AppointmentNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return {"steps": len(steps), "jobs_created": len(created)}


@router.post("/{appointment_id}/preparation/steps", status_code=201)
async def add_step(
    appointment_id: str,
    body: StepIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.appointment.manage"))],
) -> dict:
    """เพิ่มขั้นเตรียมตัว — ข้อกำหนดทางการแพทย์ต้องแนบ source_document เสมอ"""
    try:
        step = await svc.add_preparation_step(
            session,
            scope,
            appointment_id=appointment_id,
            kind=body.kind,
            label=body.label,
            due_at=body.due_at,
            order=body.order,
            source_document=body.source_document,
        )
    except svc.PreparationRuleViolation as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except svc.AppointmentNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return {"step_id": step.step_id, "kind": step.kind, "due_at": step.due_at}


@router.post("/preparation/steps/{step_id}/done")
async def complete_step(step_id: str, scope: ScopeDep, session: SessionDep) -> dict:
    try:
        step = await svc.complete_step(session, scope, step_id)
    except svc.AppointmentNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return {"step_id": step.step_id, "status": step.status}


@router.get("/{appointment_id}/readiness")
async def readiness(appointment_id: str, scope: ScopeDep, session: SessionDep) -> dict:
    try:
        return await svc.readiness(session, scope, appointment_id)
    except svc.AppointmentNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{appointment_id}/visit-brief")
async def visit_brief(appointment_id: str, scope: ScopeDep, session: SessionDep) -> dict:
    """สิ่งที่ควรแจ้ง/ถามคุณหมอ + สรุปยาปัจจุบัน"""
    try:
        return await svc.visit_brief(session, scope, appointment_id)
    except svc.AppointmentNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{appointment_id}/complete")
async def complete(
    appointment_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.appointment.manage"))],
    attended: bool = True,
) -> dict:
    try:
        appointment = await svc.complete_appointment(
            session, scope, appointment_id, attended=attended
        )
    except svc.AppointmentNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return _serialize(appointment)
