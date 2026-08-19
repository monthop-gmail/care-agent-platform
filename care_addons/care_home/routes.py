from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep
from core.auth import require_permission
from core.tenancy import Principal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from care_addons.care_home import services as svc

router = APIRouter(prefix="/api/care/home", tags=["care: home"])


def principal_of(user: Any) -> Principal:
    return Principal(
        type="human",
        id=f"user-{user.id}",
        display_name=getattr(user, "full_name", "") or getattr(user, "email", ""),
    )


class ItemIn(BaseModel):
    patient_id: str
    kind: str
    label: str = Field(min_length=1)
    home_location: str = ""
    state: str = "unknown"


class StateIn(BaseModel):
    state: str
    location: str | None = None


class SetAsideIn(BaseModel):
    item_ids: list[str] = Field(min_length=1)
    for_date: date
    reason: str = Field(min_length=1)


@router.post("", status_code=201)
async def add_item(
    body: ItemIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.home.manage"))],
) -> dict:
    try:
        item = await svc.add_item(
            session,
            scope,
            patient_id=body.patient_id,
            kind=body.kind,
            label=body.label,
            home_location=body.home_location,
            state=body.state,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return svc.as_home_item(item)


@router.post("/{item_id}/state")
async def set_state(
    item_id: str,
    body: StateIn,
    scope: ScopeDep,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("care.home.manage"))],
) -> dict:
    """🔒 ผู้ยืนยันคือผู้ใช้ที่ล็อกอินอยู่ — ระบบเดาสถานะเองไม่ได้"""
    try:
        item = await svc.set_state(
            session, scope, item_id, state=body.state,
            confirmed_by=principal_of(user), location=body.location,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (svc.HomeRuleViolation, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return svc.as_home_item(item)


@router.post("/{item_id}/unsure")
async def mark_unsure(
    item_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.home.manage"))],
) -> dict:
    """ผู้ป่วยตอบว่า "จำไม่ได้" — ระบบเสนอทางที่ปลอดภัย ไม่เดาแทน"""
    try:
        result = await svc.mark_unsure(session, scope, item_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return result


@router.get("/where")
async def where_is(
    patient_id: str,
    label: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.home.read"))],
) -> dict:
    return await svc.where_is(session, scope, patient_id, label=label)


@router.post("/set-aside")
async def set_aside(
    body: SetAsideIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.home.manage"))],
) -> list[dict]:
    try:
        items = await svc.set_aside(
            session, scope, body.item_ids, for_date=body.for_date, reason=body.reason
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return [svc.as_home_item(item) for item in items]


@router.get("/prepared")
async def prepared(
    patient_id: str,
    day: date,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.home.read"))],
) -> list[dict]:
    return [svc.as_home_item(i) for i in await svc.prepared_for(session, scope, patient_id, day)]
