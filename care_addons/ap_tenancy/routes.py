from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from core.auth import get_current_user, require_permission
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from care_addons.ap_tenancy import services as svc
from care_addons.ap_tenancy.deps import ScopeDep, SessionDep, principal_of
from care_addons.ap_tenancy.models import ApConsentGrant, ApTenant

router = APIRouter(prefix="/api/platform", tags=["platform: tenancy"])


class TenantIn(BaseModel):
    tenant_id: str
    display_name: str = ""
    timezone: str = "Asia/Bangkok"


class MemberIn(BaseModel):
    user_id: int
    role: str = "member"


class ConsentIn(BaseModel):
    subject_id: str
    grantee_id: str
    grantee_type: str = "human"
    scopes: list[str] = Field(min_length=1)
    purpose: str = "daily_care"
    expires_at: datetime | None = None


@router.post("/tenants", status_code=201)
async def create_tenant(
    body: TenantIn,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("platform.tenancy.manage"))],
) -> dict:
    tenant = await svc.create_tenant(session, body.tenant_id, body.display_name, body.timezone)
    await svc.add_member(session, tenant.tenant_id, user.id, role="owner")
    await session.commit()
    return {"tenant_id": tenant.tenant_id, "display_name": tenant.display_name}


@router.get("/tenants")
async def my_tenants(
    session: SessionDep, user: Annotated[Any, Depends(get_current_user)]
) -> list[dict]:
    from care_addons.ap_tenancy.models import ApTenantMember

    if getattr(user, "is_superuser", False):
        rows = (await session.execute(select(ApTenant))).scalars()
        return [{"tenant_id": t.tenant_id, "display_name": t.display_name} for t in rows]
    result = await session.execute(
        select(ApTenant)
        .join(ApTenantMember, ApTenantMember.tenant_id == ApTenant.tenant_id)
        .where(ApTenantMember.user_id == user.id)
    )
    return [{"tenant_id": t.tenant_id, "display_name": t.display_name} for t in result.scalars()]


@router.post("/tenants/{tenant_id}/members", status_code=201)
async def add_member(
    tenant_id: str,
    body: MemberIn,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("platform.tenancy.manage"))],
) -> dict:
    if await session.get(ApTenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="ไม่พบ tenant")
    member = await svc.add_member(session, tenant_id, body.user_id, body.role)
    await session.commit()
    return {"tenant_id": member.tenant_id, "user_id": member.user_id, "role": member.role}


@router.post("/consents", status_code=201)
async def grant_consent(
    body: ConsentIn,
    scope: ScopeDep,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("platform.consent.manage"))],
) -> dict:
    grant = await svc.grant_consent(
        session,
        scope,
        subject_id=body.subject_id,
        grantee=svc.Principal(type=body.grantee_type, id=body.grantee_id),
        scopes=body.scopes,
        purpose=body.purpose,
        granted_by=principal_of(user),
        expires_at=body.expires_at,
    )
    await session.commit()
    return {"grant_id": grant.grant_id, "scopes": grant.scopes, "subject_id": grant.subject_id}


@router.get("/consents")
async def list_consents(scope: ScopeDep, session: SessionDep, subject_id: str | None = None) -> list[dict]:
    stmt = select(ApConsentGrant)
    if subject_id:
        stmt = stmt.where(ApConsentGrant.subject_id == subject_id)
    result = await session.execute(svc.scoped(stmt, ApConsentGrant, scope))
    return [
        {
            "grant_id": g.grant_id,
            "subject_id": g.subject_id,
            "grantee_id": g.grantee_id,
            "scopes": g.scopes,
            "purpose": g.purpose,
            "active": g.active and g.revoked_at is None,
            "expires_at": g.expires_at,
        }
        for g in result.scalars()
    ]


@router.delete("/consents/{grant_id}", status_code=204)
async def revoke_consent(
    grant_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("platform.consent.manage"))],
) -> None:
    try:
        await svc.revoke_consent(session, scope, grant_id)
    except svc.ConsentDenied as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
