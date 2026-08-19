from __future__ import annotations

from addons.tenancy.deps import ScopeDep, SessionDep
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from care_addons.care_journal import services as svc

router = APIRouter(prefix="/api/care/journal", tags=["care: journal"])


class EntryIn(BaseModel):
    patient_id: str
    text: str
    entry_type: str = "observation"
    target_specialty: str | None = None


@router.post("", status_code=201)
async def record_entry(body: EntryIn, scope: ScopeDep, session: SessionDep) -> dict:
    try:
        entry = await svc.record(
            session,
            scope,
            patient_id=body.patient_id,
            text=body.text,
            entry_type=body.entry_type,
            target_specialty=body.target_specialty,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return {"entry_id": entry.entry_id, "status": entry.status, "classification": entry.classification}


@router.get("/questions")
async def questions(
    patient_id: str, scope: ScopeDep, session: SessionDep, specialty: str | None = None
) -> list[dict]:
    entries = await svc.open_questions(session, scope, patient_id, specialty=specialty)
    return [{"entry_id": e.entry_id, "text": e.text, "recorded_at": e.recorded_at} for e in entries]


@router.get("/visit-brief")
async def visit_brief(
    patient_id: str, scope: ScopeDep, session: SessionDep, specialty: str | None = None
) -> dict:
    return await svc.visit_brief(session, scope, patient_id, specialty=specialty)
