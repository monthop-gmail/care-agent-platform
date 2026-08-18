from __future__ import annotations

from typing import Annotated, Any

from core.auth import require_permission
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from care_addons.ap_tenancy.deps import ScopeDep, SessionDep
from care_addons.ap_tenancy.services import scoped
from care_addons.care_line import services as svc
from care_addons.care_line.models import CareLineBinding

router = APIRouter(prefix="/api/care/line", tags=["care: line"])


class PairingIn(BaseModel):
    patient_id: str
    principal_id: str
    role: str = "patient"
    display_name: str = ""
    ttl_minutes: int = svc.CODE_TTL_MINUTES


@router.post("/pairing-codes", status_code=201)
async def create_pairing_code(
    body: PairingIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.line.manage"))],
) -> dict:
    """ออกรหัสจับคู่ให้ผู้ป่วยหรือผู้ดูแลไปพิมพ์ในแชท LINE

    รหัสแสดงครั้งเดียวตรงนี้ — ไม่ถูกบันทึกลง audit เพราะใครถือรหัสก็ผูกบัญชีแทนได้
    """
    try:
        record = await svc.create_pairing_code(
            session,
            scope,
            patient_id=body.patient_id,
            principal_id=body.principal_id,
            role=body.role,
            display_name=body.display_name,
            ttl_minutes=body.ttl_minutes,
        )
    except svc.PairingError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return {
        "code": record.code,
        "expires_at": record.expires_at,
        "instruction": f"พิมพ์ในแชท LINE ว่า: ผูก {record.code}",
    }


@router.get("/bindings")
async def list_bindings(
    scope: ScopeDep, session: SessionDep, patient_id: str | None = None
) -> list[dict]:
    stmt = select(CareLineBinding).where(CareLineBinding.active.is_(True))
    if patient_id:
        stmt = stmt.where(CareLineBinding.patient_id == patient_id)
    result = await session.execute(scoped(stmt, CareLineBinding, scope))
    return [
        {
            "binding_id": b.binding_id,
            "patient_id": b.patient_id,
            "principal_id": b.principal_id,
            "role": b.role,
            "display_name": b.display_name,
            "channel_id": b.channel_id,
        }
        for b in result.scalars()
    ]


@router.delete("/bindings/{binding_id}", status_code=204)
async def unbind(
    binding_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.line.manage"))],
) -> None:
    binding = await session.get(CareLineBinding, binding_id)
    if binding is None or binding.tenant_id != scope.tenant_id:
        raise HTTPException(status_code=404, detail="ไม่พบการผูกบัญชีนี้")
    binding.active = False
    await session.commit()
