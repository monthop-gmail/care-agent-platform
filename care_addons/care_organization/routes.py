from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep
from core.auth import require_permission
from core.tenancy import Principal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from care_addons.care_organization import services as svc

router = APIRouter(prefix="/api/care/organizations", tags=["care: organization"])


def principal_of(user: Any) -> Principal:
    return Principal(
        type="human",
        id=f"user-{user.id}",
        display_name=getattr(user, "full_name", "") or getattr(user, "email", ""),
    )


class OrgIn(BaseModel):
    name: str = Field(min_length=1)
    kind: str
    external_ref: str | None = None
    contact: str | None = None
    note: str | None = None


class MemberIn(BaseModel):
    principal_id: str = Field(min_length=1)
    display_name: str = ""
    role: str = "doctor"
    starts_on: date | None = None
    ends_on: date | None = None


class EndMemberIn(BaseModel):
    reason: str = Field(min_length=1)


class AccessIn(BaseModel):
    patient_id: str
    principal_id: str
    authority_basis: str = Field(min_length=1)
    scopes: list[str] | None = None
    expires_at: datetime | None = None


@router.post("", status_code=201)
async def add_organization(
    body: OrgIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.organization.manage"))],
) -> dict:
    try:
        org = await svc.add_organization(
            session, scope, name=body.name, kind=body.kind,
            external_ref=body.external_ref, contact=body.contact, note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return svc.as_organization(org)


@router.get("")
async def list_organizations(
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.organization.read"))],
    kind: str | None = None,
) -> list[dict]:
    return [svc.as_organization(o) for o in await svc.organizations(session, scope, kind=kind)]


@router.post("/{organization_id}/members", status_code=201)
async def add_member(
    organization_id: str,
    body: MemberIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.organization.manage"))],
) -> dict:
    try:
        membership = await svc.add_member(
            session,
            scope,
            organization_id,
            principal=Principal(type="human", id=body.principal_id, display_name=body.display_name),
            role=body.role,
            display_name=body.display_name,
            starts_on=body.starts_on,
            ends_on=body.ends_on,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (svc.OrganizationRuleViolation, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return svc.as_membership(membership)


@router.post("/members/{membership_id}/end")
async def end_member(
    membership_id: str,
    body: EndMemberIn,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.organization.manage"))],
) -> dict:
    """คนออกจากองค์กร — สิทธิ์ที่ผูกกับสมาชิกภาพนี้ใช้ไม่ได้ทันที"""
    try:
        membership = await svc.end_membership(session, scope, membership_id, reason=body.reason)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return svc.as_membership(membership)


@router.post("/{organization_id}/access", status_code=201)
async def grant_access(
    organization_id: str,
    body: AccessIn,
    scope: ScopeDep,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("care.organization.manage"))],
) -> dict:
    """ให้หมอ 'คนนี้ ในฐานะแพทย์ขององค์กรนั้น' อ่านข้อมูลได้"""
    try:
        grant = await svc.grant_clinical_access(
            session,
            scope,
            patient_id=body.patient_id,
            organization_id=organization_id,
            principal=Principal(type="human", id=body.principal_id),
            granted_by=principal_of(user),
            authority_basis=body.authority_basis,
            scopes=body.scopes,
            expires_at=body.expires_at,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (svc.OrganizationRuleViolation, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    from care_addons.ap_consent.services import as_consent_grant

    return as_consent_grant(grant)


@router.get("/access")
async def open_access(
    patient_id: str,
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("care.organization.read"))],
) -> list[dict]:
    """ใครเข้าถึงข้อมูลผู้ป่วยรายนี้ได้บ้างตอนนี้ — สิทธิ์ที่ค้างเปิดคือความเสี่ยงที่มองไม่เห็น"""
    return await svc.open_access(session, scope, patient_id)
