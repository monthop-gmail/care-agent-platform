from __future__ import annotations

from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep, principal_of
from core.auth import require_permission
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from care_addons.ap_policy.engine import PolicyDenied
from care_addons.care_medication import services as svc

router = APIRouter(prefix="/api/care/medications", tags=["care: medication"])


class ProposeIn(BaseModel):
    patient_id: str
    name: str
    schedule: list[dict]
    instruction_source: str
    medication_id: str | None = None
    route: str = "oral"
    prescribed_by: dict | None = None
    reason: str | None = None


class StopIn(BaseModel):
    patient_id: str
    reason: str


def _serialize(v) -> dict:
    return {
        "version_id": v.version_id,
        "medication_id": v.medication_id,
        "name": v.name,
        "schedule": v.schedule,
        "status": v.status,
        "instruction_source": v.instruction_source,
        "prescribed_by": v.prescribed_by,
        "effective_from": v.effective_from,
        "superseded_by": v.superseded_by,
        "confirmed_by": v.confirmed_by,
    }


@router.post("/propose", status_code=201)
async def propose(
    body: ProposeIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.medication.manage"))],
) -> dict:
    """เสนอคำสั่งใช้ยา — ได้ status `proposed` เสมอ ต้องมีคนยืนยันจึงมีผล"""
    try:
        version = await svc.propose_version(
            session,
            scope,
            patient_id=body.patient_id,
            name=body.name,
            schedule=body.schedule,
            instruction_source=body.instruction_source,
            medication_id=body.medication_id,
            route=body.route,
            prescribed_by=body.prescribed_by,
            reason=body.reason,
        )
    except (ValueError, svc.MedicationRuleViolation) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return _serialize(version)


@router.post("/{version_id}/confirm")
async def confirm(
    version_id: str,
    scope: ScopeDep,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("care.medication.manage"))],
) -> dict:
    """ยืนยันคำสั่งใช้ยา — คนเท่านั้น (ADR-0006)"""
    try:
        version = await svc.confirm_version(
            session, scope, version_id, confirmed_by=principal_of(user)
        )
    except svc.MedicationRuleViolation as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except PolicyDenied as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return _serialize(version)


@router.post("/{medication_id}/stop")
async def stop(
    medication_id: str,
    body: StopIn,
    scope: ScopeDep,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("care.medication.manage"))],
) -> dict:
    try:
        version = await svc.stop_medication(
            session,
            scope,
            medication_id,
            patient_id=body.patient_id,
            stopped_by=principal_of(user),
            reason=body.reason,
        )
    except svc.MedicationRuleViolation as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return _serialize(version)


@router.get("/current")
async def current(patient_id: str, scope: ScopeDep, session: SessionDep) -> list[dict]:
    """ตอนนี้ต้องกินยังไง — active เท่านั้น"""
    return [_serialize(v) for v in await svc.current_regimen(session, scope, patient_id)]


@router.get("/{medication_id}/history")
async def get_history(medication_id: str, scope: ScopeDep, session: SessionDep) -> list[dict]:
    """เมื่อก่อนกินยังไง — ทั้ง chain"""
    return [_serialize(v) for v in await svc.history(session, scope, medication_id)]


@router.get("/reconciliation")
async def reconciliation(patient_id: str, scope: ScopeDep, session: SessionDep) -> dict:
    """สรุปยาเพื่อพบหมอ"""
    return await svc.reconciliation_summary(session, scope, patient_id)


@router.get("/doses")
async def doses(patient_id: str, relation: str, scope: ScopeDep, session: SessionDep) -> list[dict]:
    try:
        return await svc.doses_for_meal(session, scope, patient_id, relation)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
