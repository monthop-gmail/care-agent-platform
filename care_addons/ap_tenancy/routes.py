"""shim — endpoint เดิมของเรา ชี้ไปที่ service ของ kernel

kernel มี `/api/tenancy/...` ของตัวเองแล้ว แต่ client ของเรา (เทส · seed · เอกสาร)
ใช้ `/api/platform/...` อยู่ — เก็บ path เดิมไว้หนึ่งรอบตาม ADR-0003
รอบที่ 2 ให้ย้าย client ไป `/api/tenancy` แล้วลบไฟล์นี้

consent ย้ายไป `ap_consent` แล้ว (path `/api/platform/consents` เหมือนเดิม)
"""

from __future__ import annotations

from typing import Annotated, Any

from addons.tenancy.deps import SessionDep
from addons.tenancy.models import Tenant, TenantMember
from addons.tenancy.services import add_member as _add_member
from addons.tenancy.services import create_tenant as _create_tenant
from core.auth import get_current_user, require_permission
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

router = APIRouter(prefix="/api/platform", tags=["platform: tenancy (deprecated)"])


class TenantIn(BaseModel):
    tenant_id: str
    display_name: str = ""
    timezone: str = "Asia/Bangkok"


class MemberIn(BaseModel):
    user_id: int
    role: str = "member"


@router.post("/tenants", status_code=201, deprecated=True)
async def create_tenant(
    body: TenantIn,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("platform.tenancy.manage"))],
) -> dict:
    """เทียบเท่า `POST /api/tenancy/tenants` ของ kernel"""
    tenant = await _create_tenant(session, body.tenant_id, body.display_name, body.timezone)
    await _add_member(session, tenant.tenant_id, user.id, role="owner")
    await session.commit()
    return {"tenant_id": tenant.tenant_id, "display_name": tenant.display_name}


@router.get("/tenants", deprecated=True)
async def my_tenants(
    session: SessionDep, user: Annotated[Any, Depends(get_current_user)]
) -> list[dict]:
    if getattr(user, "is_superuser", False):
        rows = (await session.execute(select(Tenant))).scalars()
        return [{"tenant_id": t.tenant_id, "display_name": t.display_name} for t in rows]
    result = await session.execute(
        select(Tenant)
        .join(TenantMember, TenantMember.tenant_id == Tenant.tenant_id)
        .where(TenantMember.user_id == user.id)
    )
    return [{"tenant_id": t.tenant_id, "display_name": t.display_name} for t in result.scalars()]


@router.post("/tenants/{tenant_id}/members", status_code=201, deprecated=True)
async def add_member(
    tenant_id: str,
    body: MemberIn,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("platform.tenancy.manage"))],
) -> dict:
    if await session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="ไม่พบ tenant")
    member = await _add_member(session, tenant_id, body.user_id, body.role)
    await session.commit()
    return {"tenant_id": member.tenant_id, "user_id": member.user_id, "role": member.role}
