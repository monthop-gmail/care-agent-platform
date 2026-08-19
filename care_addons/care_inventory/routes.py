from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep
from core.auth import require_permission
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from care_addons.care_inventory import services as svc

router = APIRouter(prefix="/api/care/inventory", tags=["care: inventory"])


class ItemIn(BaseModel):
    patient_id: str
    name: str = Field(min_length=1)
    category: str
    quantity: float = 1.0
    unit: str = ""
    location: str = ""
    expires_on: date | None = None
    opened_on: date | None = None
    note: str | None = None


class CloseIn(BaseModel):
    status: str
    reason: str = ""


@router.post("", status_code=201)
async def add_item(
    body: ItemIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.inventory.manage"))],
) -> dict:
    try:
        item = await svc.add_item(
            session,
            scope,
            patient_id=body.patient_id,
            name=body.name,
            category=body.category,
            quantity=body.quantity,
            unit=body.unit,
            location=body.location,
            expires_on=body.expires_on,
            opened_on=body.opened_on,
            note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return svc.as_inventory_item(item)


@router.get("")
async def list_items(
    patient_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.inventory.read"))],
    name: str | None = None,
) -> list[dict]:
    return [
        svc.as_inventory_item(item)
        for item in await svc.in_stock(session, scope, patient_id, name=name)
    ]


@router.get("/check")
async def check_before_buying(
    patient_id: str,
    name: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.inventory.read"))],
) -> dict:
    """"ซื้ออีกไหม" — คำตอบเป็นข้อมูล ไม่ใช่คำสั่ง (ไม่มี field ที่แปลว่า 'ห้ามซื้อ')"""
    result = await svc.check_before_buying(session, scope, patient_id, name=name)
    await session.commit()
    return result


@router.get("/expiring")
async def expiring(
    patient_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.inventory.read"))],
    within_days: int = svc.DEFAULT_EXPIRY_WARNING_DAYS,
) -> dict:
    return await svc.expiring_soon(session, scope, patient_id, within_days=within_days)


@router.post("/{item_id}/close")
async def close_item(
    item_id: str,
    body: CloseIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.inventory.manage"))],
) -> dict:
    try:
        item = await svc.close_item(session, scope, item_id, status=body.status, reason=body.reason)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return svc.as_inventory_item(item)
