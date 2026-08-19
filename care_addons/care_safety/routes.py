from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep
from core.auth import require_permission
from core.tenancy import Principal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from care_addons.care_safety import services as svc

router = APIRouter(prefix="/api/care/safety", tags=["care: safety"])


def principal_of(user: Any) -> Principal:
    return Principal(
        type="human",
        id=f"user-{user.id}",
        display_name=getattr(user, "full_name", "") or getattr(user, "email", ""),
    )


class SignalIn(BaseModel):
    patient_id: str
    kind: str
    source: dict
    observed_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    raw: dict | None = None


class AcknowledgeIn(BaseModel):
    note: str = ""


class CloseIn(BaseModel):
    state: str
    note: str = ""


@router.post("/signals", status_code=201)
async def report_signal(
    body: SignalIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.safety.manage"))],
) -> dict:
    """ทางเข้าของ IoT/wearable — บันทึกทุกสัญญาณ ปลุกคนเฉพาะที่ผ่านเกณฑ์"""
    try:
        event = await svc.report_signal(
            session,
            scope,
            patient_id=body.patient_id,
            kind=body.kind,
            source=body.source,
            observed_at=body.observed_at,
            confidence=body.confidence,
            raw=body.raw,
        )
    except (ValueError, svc.SafetyRuleViolation) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return svc.as_safety_event(event)


@router.get("/events")
async def list_open(
    patient_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.safety.read"))],
) -> dict:
    """🔒 รายการว่างไม่ได้แปลว่าปลอดภัย — อุปกรณ์อาจเงียบเพราะแบตหมด (safety_rules ข้อ 5)"""
    events = await svc.open_events(session, scope, patient_id)
    return {
        "open_events": [svc.as_safety_event(e) for e in events],
        "note": "รายการนี้คือสัญญาณที่ระบบได้รับเท่านั้น — ไม่ได้แปลว่าที่เหลือปลอดภัย",
    }


@router.post("/events/{safety_event_id}/acknowledge")
async def acknowledge(
    safety_event_id: str,
    body: AcknowledgeIn,
    scope: ScopeDep,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("care.safety.manage"))],
) -> dict:
    try:
        event = await svc.acknowledge(
            session, scope, safety_event_id,
            acknowledged_by=principal_of(user), note=body.note,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except svc.SafetyRuleViolation as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return svc.as_safety_event(event)


@router.post("/events/{safety_event_id}/close")
async def close_event(
    safety_event_id: str,
    body: CloseIn,
    scope: ScopeDep,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("care.safety.manage"))],
) -> dict:
    try:
        event = await svc.close_event(
            session, scope, safety_event_id, state=body.state,
            closed_by=principal_of(user), note=body.note,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (ValueError, svc.SafetyRuleViolation) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return svc.as_safety_event(event)
