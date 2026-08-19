from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep
from core.auth import require_permission
from core.tenancy import Principal, scoped
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from care_addons.ap_consent import services as svc
from care_addons.ap_consent.models import ApConsentGrant

router = APIRouter(prefix="/api/platform/consents", tags=["platform: consent"])


def principal_of(user: Any) -> Principal:
    return Principal(
        type="human",
        id=f"user-{user.id}",
        display_name=getattr(user, "full_name", "") or getattr(user, "email", ""),
    )


class ConsentIn(BaseModel):
    subject_id: str
    grantee_id: str
    grantee_type: str = "human"
    scopes: list[str] = Field(min_length=1)
    purpose: str = "daily_care"
    # บังคับเมื่อผู้ให้ความยินยอมไม่ใช่เจ้าของข้อมูลเอง (consent/v1)
    authority_basis: str | None = None
    expires_at: datetime | None = None


class RevokeIn(BaseModel):
    reason: str = Field(min_length=1)


@router.post("", status_code=201)
async def grant_consent(
    body: ConsentIn,
    scope: ScopeDep,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("platform.consent.manage"))],
) -> dict:
    try:
        grant = await svc.grant_consent(
            session,
            scope,
            subject_id=body.subject_id,
            grantee=Principal(type=body.grantee_type, id=body.grantee_id),
            scopes=body.scopes,
            purpose=body.purpose,
            granted_by=principal_of(user),
            authority_basis=body.authority_basis,
            expires_at=body.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return {"grant_id": grant.grant_id, "scopes": grant.scopes, "subject_id": grant.subject_id}


@router.get("")
async def list_consents(
    scope: ScopeDep, session: SessionDep, subject_id: str | None = None
) -> list[dict]:
    stmt = select(ApConsentGrant)
    if subject_id:
        stmt = stmt.where(ApConsentGrant.subject_id == subject_id)
    result = await session.execute(scoped(stmt, ApConsentGrant, scope))
    return [
        {
            "grant_id": g.grant_id,
            "subject_id": g.subject_id,
            "grantee_id": g.grantee_id,
            "scopes": g.scopes,
            "purpose": g.purpose,
            # สถานะคำนวณจาก revoked_at/expires_at เท่านั้น — ไม่มีคอลัมน์เก็บซ้ำ (consent/v1)
            "revoked_at": g.revoked_at,
            "revoked_reason": g.revoked_reason,
            "authority_basis": g.authority_basis,
            "expires_at": g.expires_at,
        }
        for g in result.scalars()
    ]


@router.delete("/{grant_id}", status_code=204)
async def revoke_consent(
    grant_id: str,
    body: RevokeIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("platform.consent.manage"))],
) -> None:
    """เพิกถอน — ต้องระบุเหตุผลเสมอ (consent/v1 dependentRequired)"""
    try:
        await svc.revoke_consent(session, scope, grant_id, reason=body.reason)
    except svc.ConsentDenied as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
