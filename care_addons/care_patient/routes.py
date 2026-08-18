from __future__ import annotations

from typing import Annotated, Any

from core.auth import require_permission
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from care_addons.ap_tenancy.deps import ScopeDep, SessionDep
from care_addons.ap_tenancy.services import ConsentDenied
from care_addons.care_patient import services as svc

router = APIRouter(prefix="/api/care/patients", tags=["care: patients"])


class PatientIn(BaseModel):
    display_name: str
    timezone: str = "Asia/Bangkok"
    care_profile: dict = {}
    channels: list[str] = ["app"]
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None


class CaregiverIn(BaseModel):
    principal_id: str
    display_name: str
    relation: str = ""
    channel: str = "app"


class TeamIn(BaseModel):
    caregiver_id: str
    escalation_order: int = 1
    is_emergency_contact: bool = False


def _serialize(p) -> dict:
    return {
        "patient_id": p.patient_id,
        "display_name": p.display_name,
        "timezone": p.timezone,
        "care_profile": p.care_profile,
        "channels": p.channels,
        "status": p.status,
    }


@router.post("", status_code=201)
async def create_patient(
    body: PatientIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.patient.manage"))],
) -> dict:
    quiet = (
        (body.quiet_hours_start, body.quiet_hours_end)
        if body.quiet_hours_start and body.quiet_hours_end
        else None
    )
    patient = await svc.create_patient(
        session,
        scope,
        display_name=body.display_name,
        timezone=body.timezone,
        care_profile=body.care_profile,
        channels=body.channels,
        quiet_hours=quiet,
    )
    await session.commit()
    return _serialize(patient)


@router.get("")
async def list_patients(scope: ScopeDep, session: SessionDep) -> list[dict]:
    return [_serialize(p) for p in await svc.list_patients(session, scope)]


@router.get("/{patient_id}")
async def get_patient(patient_id: str, scope: ScopeDep, session: SessionDep) -> dict:
    try:
        return _serialize(await svc.get_patient(session, scope, patient_id))
    except svc.PatientNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ConsentDenied as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.post("/{patient_id}/care-profile")
async def update_profile(
    patient_id: str,
    changes: dict,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.patient.manage"))],
) -> dict:
    try:
        patient = await svc.update_care_profile(session, scope, patient_id, changes)
    except ConsentDenied as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    await session.commit()
    return _serialize(patient)


@router.post("/caregivers", status_code=201)
async def add_caregiver(
    body: CaregiverIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.patient.manage"))],
) -> dict:
    caregiver = await svc.add_caregiver(
        session,
        scope,
        principal_id=body.principal_id,
        display_name=body.display_name,
        relation=body.relation,
        channel=body.channel,
    )
    await session.commit()
    return {"caregiver_id": caregiver.caregiver_id, "principal_id": caregiver.principal_id}


@router.post("/{patient_id}/care-team", status_code=201)
async def assign_team(
    patient_id: str,
    body: TeamIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.patient.manage"))],
) -> dict:
    member = await svc.assign_to_care_team(
        session,
        scope,
        patient_id=patient_id,
        caregiver_id=body.caregiver_id,
        escalation_order=body.escalation_order,
        is_emergency_contact=body.is_emergency_contact,
    )
    await session.commit()
    return {"patient_id": member.patient_id, "caregiver_id": member.caregiver_id}
