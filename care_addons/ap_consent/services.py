"""ความยินยอมเข้าถึงข้อมูลของบุคคล — conform `consent/v1` ของ agent-platform

ย้ายมาจาก `ap_tenancy` ตอน tenancy ขึ้น kernel · primitives ของ tenant มาจาก `core.tenancy`

สองด่านเสมอ (ADR-0007):
    RBAC ของ pstack (ทำ action นี้ได้ไหม) → consent ที่นี่ (กับ subject รายนี้ ตอนนี้ ได้ไหม)
"""

from __future__ import annotations

from datetime import datetime

from core.clock import now
from core.tenancy import Principal, TenantScope, assert_same_tenant, new_id, scoped, validate_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_consent.models import ApConsentGrant


class ConsentDenied(PermissionError):
    pass


async def grant_consent(
    session: AsyncSession,
    scope: TenantScope,
    *,
    subject_id: str,
    grantee: Principal,
    scopes: list[str],
    purpose: str = "daily_care",
    granted_by: Principal,
    authority_basis: str | None = None,
    expires_at: datetime | None = None,
) -> ApConsentGrant:
    """สร้างความยินยอมหนึ่งใบ — conform `consent/v1`

    `authority_basis` บังคับเมื่อผู้ให้ความยินยอมไม่ใช่เจ้าของข้อมูลเอง
    (contract บอกว่า optional แต่เราบังคับ เพราะโดเมนนี้ผู้ให้แทนคือกรณีปกติ
    ไม่ใช่ข้อยกเว้น — ถ้าไม่บันทึก audit จะตอบไม่ได้ว่าทำไมคนนั้นให้แทนได้)
    """
    if not scopes:
        raise ValueError("consent ต้องระบุ scope อย่างน้อยหนึ่งอย่าง — grant ที่ไม่มี scope ไม่มีความหมาย")
    if not purpose:
        raise ValueError("consent ต้องระบุ purpose — ความยินยอมที่ไม่บอกวัตถุประสงค์ตอบ audit ไม่ได้")
    if granted_by.id != subject_id and not authority_basis:
        raise ValueError(
            f"{granted_by.id} ให้ความยินยอมแทน {subject_id} จึงต้องระบุ authority_basis "
            f"ว่าให้แทนโดยอำนาจอะไร (ผู้อนุบาล · หนังสือมอบอำนาจ · ผู้ปกครองตามกฎหมาย)"
        )
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
        authority_basis=authority_basis,
        workspace_id=scope.workspace_id,
        granted_at=now(),
        expires_at=expires_at,
    )
    session.add(grant)
    await session.flush()
    return grant


async def revoke_consent(
    session: AsyncSession, scope: TenantScope, grant_id: str, *, reason: str
) -> None:
    """เพิกถอนความยินยอม — มีผลทันที

    `reason` บังคับตาม consent/v1 (`dependentRequired`) เพราะ "ถอนเพราะเจ้าของเปลี่ยนใจ"
    กับ "ถอนเพราะผู้รับละเมิดเงื่อนไข" ต่างกันมากตอน audit
    """
    if not reason or not reason.strip():
        raise ValueError("การเพิกถอนต้องระบุเหตุผล — consent/v1 บังคับ revoked_reason")
    grant = await session.get(ApConsentGrant, grant_id)
    if grant is None:
        raise ConsentDenied(f"ไม่พบ consent grant: {grant_id}")
    assert_same_tenant(scope, grant)
    grant.revoked_at = now()
    grant.revoked_by_type = scope.principal.type
    grant.revoked_by_id = scope.principal.id
    grant.revoked_reason = reason.strip()
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
                # ไม่มีคอลัมน์ status — สถานะคือผลของ revoked_at/expires_at เท่านั้น
                ApConsentGrant.revoked_at.is_(None),
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


def as_consent_grant(grant: ApConsentGrant) -> dict:
    """payload ตาม `consent/v1` — ใช้ส่งออกนอกระบบและให้ payload_check validate"""
    payload: dict = {
        "grant_id": grant.grant_id,
        "tenant_id": grant.tenant_id,
        "subject_id": grant.subject_id,
        "grantee": {"type": grant.grantee_type, "id": grant.grantee_id},
        "scopes": list(grant.scopes or []),
        "purpose": grant.purpose,
        "granted_by": {"type": grant.granted_by_type, "id": grant.granted_by_id},
        "granted_at": grant.granted_at.isoformat(),
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
    }
    if grant.workspace_id:
        payload["workspace_id"] = grant.workspace_id
    if grant.authority_basis:
        payload["authority_basis"] = grant.authority_basis
    if grant.revoked_at:
        payload["revoked_at"] = grant.revoked_at.isoformat()
        payload["revoked_by"] = {"type": grant.revoked_by_type, "id": grant.revoked_by_id}
        payload["revoked_reason"] = grant.revoked_reason
    return payload


async def require_consent(
    session: AsyncSession, scope: TenantScope, *, subject_id: str, required_scope: str
) -> None:
    if not await has_consent(
        session, scope, subject_id=subject_id, required_scope=required_scope
    ):
        raise ConsentDenied(
            f"{scope.principal.id} ไม่มี consent '{required_scope}' สำหรับ {subject_id}"
        )
