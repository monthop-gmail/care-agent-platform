from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep
from core.auth import require_permission
from fastapi import APIRouter, Depends, HTTPException

from care_addons.care_orchestrator import services as svc
from care_addons.care_patient.services import get_patient

router = APIRouter(prefix="/api/care/summary", tags=["care: summary"])


@router.get("/{patient_id}")
async def read_summary(
    patient_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.summary.read"))],
    local_date: date | None = None,
) -> dict:
    """สรุปของวันนั้น — ถ้ายังไม่ถึงเวลาส่ง จะคำนวณสด ๆ ให้ดูได้แต่ไม่ส่งออก"""
    patient = await get_patient(session, scope, patient_id, required_scope="care.manage")
    day = local_date or svc.local_date_of(patient, svc.now())
    stored = await svc.existing_summary(session, scope, patient_id, day)
    if stored is not None:
        return {
            "summary_id": stored.summary_id,
            "local_date": stored.local_date.isoformat(),
            "text": stored.text,
            "facts": stored.facts,
            "sent_at": stored.sent_at.isoformat() if stored.sent_at else None,
            "recipients": stored.recipients,
        }
    facts = await svc.build_facts(session, scope, patient, day)
    return {
        "summary_id": None,
        "local_date": day.isoformat(),
        "text": svc.render(patient, facts),
        "facts": facts,
        "sent_at": None,
        "recipients": 0,
    }


@router.post("/{patient_id}/send")
async def send_summary(
    patient_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.summary.read"))],
) -> dict:
    """ส่งสรุปของวันนี้เดี๋ยวนี้ — ถ้าวันนี้ส่งไปแล้วจะไม่ส่งซ้ำ"""
    patient = await get_patient(session, scope, patient_id, required_scope="care.manage")
    row = await svc.send_daily_summary(session, scope, patient)
    if row is None:
        raise HTTPException(status_code=409, detail="สรุปของวันนี้ถูกส่งไปแล้ว")
    await session.commit()
    return {"summary_id": row.summary_id, "recipients": row.recipients, "text": row.text}
