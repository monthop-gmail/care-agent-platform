"""องค์กรภายนอกที่ครอบครัวนี้ใช้ + ใครทำงานที่ไหน

🔒 กติกาของ [ADR-0010](../../decisions/0010-organizations-are-not-tenants.md):
   1. องค์กร **ไม่ใช่ tenant** — ไม่มีข้อมูลผู้ป่วยชุดที่สอง
   2. องค์กรเป็น record แบบ tenant-scoped ไม่ใช่ทะเบียนกลาง
   3. consent ให้แก่ **บุคคล** ไม่ใช่แก่องค์กร — พนักงานใหม่ต้องไม่ได้สิทธิ์เองเงียบ ๆ
   4. สิทธิ์จริง = consent ที่ยังใช้ได้ **และ** ยังเป็นสมาชิกขององค์กรอยู่ (AND)
   6. องค์กรเขียนอะไรลงระบบโดยตรงไม่ได้ — สิ่งที่มาจากข้างนอกเป็นข้อเสนอเสมอ
"""

from __future__ import annotations

from datetime import date, datetime

from core.clock import now
from core.tenancy import Principal, TenantScope, new_id, scoped
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_consent import services as consent
from care_addons.ap_policy.services import care_action
from care_addons.care_organization.models import (
    MEMBER_ROLES,
    ORG_KINDS,
    CareOrganization,
    CareOrgMembership,
)

# ชนิดของเงื่อนไขที่โมดูลนี้เป็นเจ้าของ — `ap_consent` เก็บไว้เฉย ๆ โดยไม่รู้ความหมาย
CONDITION_KIND = "org_membership"

# scope ที่ให้ผู้ให้การรักษาได้ — 🔒 ห้ามให้ `care.manage` เพราะนั่นคือสิทธิ์ของผู้ดูแลหลัก
CLINICAL_SCOPES = ["clinical.read", "medication.read", "appointment.read", "journal.read"]


class OrganizationRuleViolation(PermissionError):
    """กติกาขององค์กรภายนอก — ไม่ใช่ error ธรรมดา"""


@care_action("organization.write", autonomous=True)
async def add_organization(
    session: AsyncSession,
    scope: TenantScope,
    *,
    name: str,
    kind: str,
    external_ref: str | None = None,
    contact: str | None = None,
    note: str | None = None,
) -> CareOrganization:
    if kind not in ORG_KINDS:
        raise ValueError(f"kind ไม่รู้จัก: {kind} — ต้องเป็นหนึ่งใน {ORG_KINDS}")
    if not name.strip():
        raise ValueError("ชื่อองค์กรว่างไม่ได้")

    org = CareOrganization(
        organization_id=new_id("org"),
        tenant_id=scope.tenant_id,
        name=name.strip(),
        kind=kind,
        external_ref=external_ref,
        contact=contact,
        note=note,
        created_at=now(),
        created_by=scope.principal.as_dict(),
    )
    session.add(org)
    await session.flush()
    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=org.organization_id,
        # ไม่ใส่ care_event_type — ทะเบียนองค์กรไม่ผูกกับผู้ป่วยรายใดรายหนึ่ง
        severity="low",
        transition={"to": "active", "reason": "บันทึกองค์กรที่ครอบครัวใช้"},
        attributes={"record_type": "organization", "name": org.name, "kind": kind},
    )
    return org


async def get_organization(
    session: AsyncSession, scope: TenantScope, organization_id: str
) -> CareOrganization:
    result = await session.execute(
        scoped(
            select(CareOrganization).where(CareOrganization.organization_id == organization_id),
            CareOrganization,
            scope,
        )
    )
    org = result.scalars().first()
    if org is None:
        raise LookupError(f"ไม่พบองค์กร {organization_id}")
    return org


async def organizations(
    session: AsyncSession, scope: TenantScope, *, kind: str | None = None
) -> list[CareOrganization]:
    stmt = select(CareOrganization)
    if kind:
        stmt = stmt.where(CareOrganization.kind == kind)
    result = await session.execute(
        scoped(stmt.order_by(CareOrganization.created_at), CareOrganization, scope)
    )
    return list(result.scalars())


@care_action("organization.membership.write", autonomous=False)
async def add_member(
    session: AsyncSession,
    scope: TenantScope,
    organization_id: str,
    *,
    principal: Principal,
    role: str = "doctor",
    display_name: str = "",
    starts_on: date | None = None,
    ends_on: date | None = None,
    decision=None,
) -> CareOrgMembership:
    """บันทึกว่าใครทำงานที่องค์กรไหน — 🔒 ต้องเป็นคน

    การเพิ่มสมาชิกคือการขยายวงคนที่อาจเข้าถึงข้อมูลผู้ป่วยได้ จึงเป็น action
    ที่ต้องมีคนรับผิดชอบ ไม่ใช่สิ่งที่ agent ทำเองจากการอ่านเอกสาร
    """
    if principal.type != "human":
        raise OrganizationRuleViolation(
            f"สมาชิกขององค์กรต้องเป็นคน — ได้รับ principal type '{principal.type}' "
            f"(องค์กรไม่ได้รับสิทธิ์ในฐานะเครื่อง · ADR-0010 ข้อ 3)"
        )
    if role not in MEMBER_ROLES:
        raise ValueError(f"role ไม่รู้จัก: {role} — ต้องเป็นหนึ่งใน {MEMBER_ROLES}")
    org = await get_organization(session, scope, organization_id)

    membership = CareOrgMembership(
        membership_id=new_id("mem"),
        tenant_id=scope.tenant_id,
        organization_id=org.organization_id,
        principal_type=principal.type,
        principal_id=principal.id,
        display_name=display_name or principal.display_name,
        role=role,
        active=True,
        starts_on=starts_on,
        ends_on=ends_on,
        created_at=now(),
    )
    session.add(membership)
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=membership.membership_id,
        severity="medium",   # วงคนที่เข้าถึงข้อมูลผู้ป่วยได้กว้างขึ้นจริงตั้งแต่วินาทีนี้
        policy_result=decision.as_policy_result() if decision else None,
        transition={"to": "active", "reason": "เพิ่มสมาชิกองค์กร"},
        attributes={
            "record_type": "org_membership",
            "organization_id": org.organization_id,
            "organization_name": org.name,
            "principal_id": principal.id,
            "role": role,
        },
    )
    return membership


@care_action("organization.membership.end", autonomous=True)
async def end_membership(
    session: AsyncSession,
    scope: TenantScope,
    membership_id: str,
    *,
    reason: str,
    on: date | None = None,
) -> CareOrgMembership:
    """คนออกจากองค์กร — 🔒 มีผลกับสิทธิ์**ทันที** ไม่ต้องรอเพิกถอน consent ทีละใบ

    นี่คือจุดที่ ADR-0010 ข้อ 4 ให้ผลจริง: ใบยินยอมทุกใบที่ผูกกับสมาชิกภาพนี้
    ใช้ไม่ได้ตั้งแต่วินาทีถัดไป โดยไม่มีใครต้องไปไล่กดอะไรเพิ่ม
    """
    if not reason.strip():
        raise ValueError("reason ว่างไม่ได้ — ต้องตอบได้ว่าตัดสิทธิ์เพราะอะไร")
    result = await session.execute(
        scoped(
            select(CareOrgMembership).where(CareOrgMembership.membership_id == membership_id),
            CareOrgMembership,
            scope,
        )
    )
    membership = result.scalars().first()
    if membership is None:
        raise LookupError(f"ไม่พบสมาชิกภาพ {membership_id}")
    if not membership.active:
        return membership

    membership.active = False
    membership.ends_on = on or now().date()
    membership.ended_reason = reason.strip()
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=membership.membership_id,
        severity="medium",
        evidence={"kind": "caregiver_confirmed", "recorded_by": scope.principal.as_dict()},
        transition={"from": "active", "to": "ended", "reason": membership.ended_reason},
        attributes={
            "record_type": "org_membership",
            "organization_id": membership.organization_id,
            "principal_id": membership.principal_id,
        },
    )
    return membership


async def active_membership(
    session: AsyncSession,
    scope: TenantScope,
    *,
    principal_id: str,
    organization_id: str,
    at: date | None = None,
) -> CareOrgMembership | None:
    """สมาชิกภาพที่ยังเป็นจริง ณ วันนั้น — None แปลว่าเข้าไม่ได้"""
    day = at or now().date()
    result = await session.execute(
        scoped(
            select(CareOrgMembership).where(
                CareOrgMembership.principal_id == principal_id,
                CareOrgMembership.organization_id == organization_id,
                CareOrgMembership.active.is_(True),
            ),
            CareOrgMembership,
            scope,
        )
    )
    for membership in result.scalars():
        if membership.starts_on and day < membership.starts_on:
            continue
        if membership.ends_on and day > membership.ends_on:
            continue
        return membership
    return None


async def _membership_condition_holds(
    session: AsyncSession, scope: TenantScope, condition: dict
) -> bool:
    """ตัวตรวจที่ `ap_consent` เรียกทุกครั้งที่ใบนี้ถูกใช้

    🔒 fail closed — ข้อมูลไม่ครบ/ไม่เจอสมาชิกภาพ = ไม่ให้ผ่าน
    """
    organization_id = condition.get("organization_id")
    if not organization_id:
        return False
    return (
        await active_membership(
            session,
            scope,
            principal_id=scope.principal.id,
            organization_id=organization_id,
        )
        is not None
    )


consent.register_condition(CONDITION_KIND, _membership_condition_holds)


@care_action("organization.access.grant", autonomous=False)
async def grant_clinical_access(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    organization_id: str,
    principal: Principal,
    granted_by: Principal,
    authority_basis: str,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
    decision=None,
):
    """ให้หมอ "คนนี้ ในฐานะแพทย์ของโรงพยาบาลนั้น" อ่านข้อมูลได้

    🔒 ใบยินยอมออกให้ **บุคคล** แล้วผูกเงื่อนไขสมาชิกภาพไว้ — ไม่ได้ออกให้องค์กร
       ถ้าออกให้องค์กร พนักงานที่เข้าใหม่พรุ่งนี้จะได้สิทธิ์ทันทีโดยครอบครัวไม่รู้ตัว
    """
    if principal.type != "human":
        raise OrganizationRuleViolation("ความยินยอมทางคลินิกให้แก่คนเท่านั้น (ADR-0010 ข้อ 3)")
    org = await get_organization(session, scope, organization_id)
    membership = await active_membership(
        session, scope, principal_id=principal.id, organization_id=organization_id
    )
    if membership is None:
        raise OrganizationRuleViolation(
            f"{principal.id} ไม่ได้เป็นสมาชิกที่ยัง active ของ '{org.name}' — "
            f"ให้สิทธิ์ก่อนที่คนจะเป็นสมาชิกไม่ได้ เพราะเงื่อนไขจะเป็นเท็จตั้งแต่วันแรก"
        )

    requested = list(scopes or CLINICAL_SCOPES)
    if "care.manage" in requested:
        raise OrganizationRuleViolation(
            "ห้ามให้ care.manage แก่ผู้ให้การรักษา — นั่นคือสิทธิ์ของผู้ดูแลหลัก (ADR-0010 ข้อ 5)"
        )

    grant = await consent.grant_consent(
        session,
        scope,
        subject_id=patient_id,
        grantee=principal,
        scopes=requested,
        purpose="clinical_care",
        granted_by=granted_by,
        authority_basis=authority_basis,
        expires_at=expires_at,
        conditions=[{"kind": CONDITION_KIND, "organization_id": organization_id}],
    )
    await audit.emit(
        session,
        scope,
        event_type="GOVERNANCE_DECISION",
        subject_type="record",
        subject_id=grant.grant_id,
        care_event_type="care.organization.access_granted",
        severity="medium",
        policy_result=decision.as_policy_result() if decision else None,
        evidence={"kind": "caregiver_confirmed", "recorded_by": granted_by.as_dict()},
        attributes={
            "record_type": "consent_grant",
            "patient_id": patient_id,
            "organization_id": organization_id,
            "organization_name": org.name,
            "grantee_id": principal.id,
            "scopes": requested,
        },
    )
    return grant


async def open_access(
    session: AsyncSession, scope: TenantScope, patient_id: str
) -> list[dict]:
    """ใครเข้าถึงข้อมูลผู้ป่วยรายนี้ได้บ้างตอนนี้ — และเงื่อนไขยังเป็นจริงไหม

    ใช้ในสรุปประจำวัน: สิทธิ์ที่ค้างเปิดไว้โดยไม่มีใครดูแลคือความเสี่ยงที่มองไม่เห็น
    """
    from care_addons.ap_consent.models import ApConsentGrant

    result = await session.execute(
        scoped(
            select(ApConsentGrant).where(
                ApConsentGrant.subject_id == patient_id,
                ApConsentGrant.revoked_at.is_(None),
            ),
            ApConsentGrant,
            scope,
        )
    )
    moment = now()
    rows = []
    for grant in result.scalars():
        if grant.expires_at is not None and grant.expires_at <= moment:
            continue
        holds = True
        organization_id = None
        for condition in grant.conditions or []:
            if condition.get("kind") == CONDITION_KIND:
                organization_id = condition.get("organization_id")
                holds = (
                    await active_membership(
                        session,
                        scope,
                        principal_id=grant.grantee_id,
                        organization_id=organization_id,
                    )
                    is not None
                )
        rows.append(
            {
                "grant_id": grant.grant_id,
                "grantee_id": grant.grantee_id,
                "scopes": list(grant.scopes or []),
                "purpose": grant.purpose,
                "organization_id": organization_id,
                "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
                "conditions_hold": holds,
            }
        )
    return rows


def as_organization(org: CareOrganization) -> dict:
    """payload ตาม `contracts/organization/v1`"""
    payload = {
        "organization_id": org.organization_id,
        "tenant_id": org.tenant_id,
        "name": org.name,
        "kind": org.kind,
        "created_at": org.created_at.isoformat(),
    }
    for field in ("external_ref", "contact", "note"):
        value = getattr(org, field)
        if value:
            payload[field] = value
    return payload


def as_membership(membership: CareOrgMembership) -> dict:
    """payload ตาม `contracts/organization/v1` membership"""
    return {
        "membership_id": membership.membership_id,
        "tenant_id": membership.tenant_id,
        "organization_id": membership.organization_id,
        "principal": {
            "type": membership.principal_type,
            "id": membership.principal_id,
            **({"display_name": membership.display_name} if membership.display_name else {}),
        },
        "role": membership.role,
        "active": membership.active,
        "starts_on": membership.starts_on.isoformat() if membership.starts_on else None,
        "ends_on": membership.ends_on.isoformat() if membership.ends_on else None,
        "ended_reason": membership.ended_reason,
    }
