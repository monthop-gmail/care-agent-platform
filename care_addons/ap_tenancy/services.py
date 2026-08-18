"""Tenant scope + consent — ด่านที่ทุก query ข้อมูล subject ต้องผ่าน

สองด่านเสมอ (ADR-0007):
    RBAC ของ pstack (ทำ action นี้ได้ไหม) → consent ที่นี่ (กับ subject รายนี้ ตอนนี้ ได้ไหม)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_tenancy.clock import now
from care_addons.ap_tenancy.ids import new_id, validate_id
from care_addons.ap_tenancy.models import (
    ApConsentGrant,
    ApTenant,
    ApTenantMember,
    ApWorkspace,
)


class TenantIsolationError(PermissionError):
    """ข้าม tenant — เป็นความผิดพลาดร้ายแรงเสมอ ไม่ใช่แค่ 403 ธรรมดา"""


class ConsentDenied(PermissionError):
    pass


@dataclass(frozen=True)
class Principal:
    """identity/v1 $defs.Principal"""

    type: str  # human | agent | service
    id: str
    display_name: str = ""

    def as_dict(self) -> dict:
        return {"type": self.type, "id": self.id, "display_name": self.display_name}


@dataclass(frozen=True)
class TenantScope:
    """context ขั้นต่ำของทุก request ที่แตะข้อมูลของ tenant (identity/v1 RequestContext)"""

    tenant_id: str
    principal: Principal
    workspace_id: str | None = None
    correlation_id: str | None = None


async def create_tenant(
    session: AsyncSession, tenant_id: str, display_name: str = "", timezone: str = "Asia/Bangkok"
) -> ApTenant:
    validate_id(tenant_id, "tenant_id")
    tenant = ApTenant(tenant_id=tenant_id, display_name=display_name or tenant_id, timezone=timezone)
    session.add(tenant)
    await session.flush()
    return tenant


async def create_workspace(
    session: AsyncSession, scope: TenantScope, workspace_id: str, display_name: str = ""
) -> ApWorkspace:
    validate_id(workspace_id, "workspace_id")
    ws = ApWorkspace(
        workspace_id=workspace_id, tenant_id=scope.tenant_id, display_name=display_name
    )
    session.add(ws)
    await session.flush()
    return ws


async def add_member(
    session: AsyncSession, tenant_id: str, user_id: int, role: str = "member"
) -> ApTenantMember:
    member = ApTenantMember(tenant_id=tenant_id, user_id=user_id, role=role)
    session.add(member)
    await session.flush()
    return member


async def is_member(session: AsyncSession, tenant_id: str, user_id: int) -> bool:
    result = await session.execute(
        select(ApTenantMember).where(
            ApTenantMember.tenant_id == tenant_id, ApTenantMember.user_id == user_id
        )
    )
    return result.scalar_one_or_none() is not None


def scoped(stmt: Select, model: type, scope: TenantScope) -> Select:
    """เติมเงื่อนไข tenant ให้ query — ทุก query ที่อ่านข้อมูล subject ต้องผ่านตัวนี้

    🔒 ห้าม select() ตารางที่มี tenant_id ตรง ๆ ใน addon โดเมน (ADR-0007)
       มี test บังคับที่ tests/test_tenant_isolation.py
    """
    column = getattr(model, "tenant_id", None)
    if column is None:
        raise TypeError(f"{model.__name__} ไม่มีคอลัมน์ tenant_id — ตารางที่เก็บข้อมูลของ tenant ต้องมีเสมอ")
    return stmt.where(column == scope.tenant_id)


def assert_same_tenant(scope: TenantScope, row: object) -> None:
    """กันการหยิบ object จากที่อื่นมาใช้ข้าม tenant"""
    row_tenant = getattr(row, "tenant_id", None)
    if row_tenant != scope.tenant_id:
        raise TenantIsolationError(
            f"ข้าม tenant: scope={scope.tenant_id} แต่ข้อมูลเป็นของ {row_tenant}"
        )


async def grant_consent(
    session: AsyncSession,
    scope: TenantScope,
    *,
    subject_id: str,
    grantee: Principal,
    scopes: list[str],
    purpose: str = "daily_care",
    granted_by: Principal,
    expires_at: datetime | None = None,
) -> ApConsentGrant:
    if not scopes:
        raise ValueError("consent ต้องระบุ scope อย่างน้อยหนึ่งอย่าง — grant ที่ไม่มี scope ไม่มีความหมาย")
    grant = ApConsentGrant(
        grant_id=new_id("grant"),
        tenant_id=scope.tenant_id,
        subject_id=validate_id(subject_id, "subject_id"),
        grantee_type=grantee.type,
        grantee_id=grantee.id,
        scopes=list(scopes),
        purpose=purpose,
        granted_by_type=granted_by.type,
        granted_by_id=granted_by.id,
        granted_at=now(),
        expires_at=expires_at,
    )
    session.add(grant)
    await session.flush()
    return grant


async def revoke_consent(session: AsyncSession, scope: TenantScope, grant_id: str) -> None:
    grant = await session.get(ApConsentGrant, grant_id)
    if grant is None:
        raise ConsentDenied(f"ไม่พบ consent grant: {grant_id}")
    assert_same_tenant(scope, grant)
    grant.revoked_at = now()
    grant.active = False
    await session.flush()


async def has_consent(
    session: AsyncSession, scope: TenantScope, *, subject_id: str, required_scope: str
) -> bool:
    """subject เข้าถึงข้อมูลของตัวเองได้เสมอ · นอกนั้นต้องมี grant ที่ยังไม่หมดอายุ/ไม่ถูกเพิกถอน"""
    if scope.principal.id == subject_id:
        return True

    result = await session.execute(
        scoped(
            select(ApConsentGrant).where(
                ApConsentGrant.subject_id == subject_id,
                ApConsentGrant.grantee_id == scope.principal.id,
                ApConsentGrant.active.is_(True),
            ),
            ApConsentGrant,
            scope,
        )
    )
    current = now()
    for grant in result.scalars():
        if grant.revoked_at is not None:
            continue
        if grant.expires_at is not None and grant.expires_at <= current:
            continue
        if required_scope in (grant.scopes or []) or "care.manage" in (grant.scopes or []):
            return True
    return False


async def require_consent(
    session: AsyncSession, scope: TenantScope, *, subject_id: str, required_scope: str
) -> None:
    if not await has_consent(
        session, scope, subject_id=subject_id, required_scope=required_scope
    ):
        raise ConsentDenied(
            f"{scope.principal.id} ไม่มี consent '{required_scope}' สำหรับ {subject_id}"
        )
