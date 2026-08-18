"""Patient / care team — ทุก read ผ่าน tenant guard + consent (ADR-0007)"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action
from care_addons.ap_tenancy.ids import new_id, validate_id
from care_addons.ap_tenancy.services import (
    TenantScope,
    assert_same_tenant,
    require_consent,
    scoped,
)
from care_addons.care_patient.models import (
    DEFAULT_CARE_PROFILE,
    CareCaregiver,
    CarePatient,
    CareTeamMember,
)


class PatientNotFound(LookupError):
    pass


async def create_patient(
    session: AsyncSession,
    scope: TenantScope,
    *,
    display_name: str,
    timezone: str = "Asia/Bangkok",
    care_profile: dict | None = None,
    channels: list[str] | None = None,
    patient_id: str | None = None,
    quiet_hours: tuple[str, str] | None = None,
) -> CarePatient:
    profile = dict(DEFAULT_CARE_PROFILE)
    for key, value in (care_profile or {}).items():
        if key not in DEFAULT_CARE_PROFILE:
            raise ValueError(f"care_profile ไม่รู้จักคีย์ '{key}' — เพิ่มใน contract ก่อน")
        profile[key] = bool(value)

    patient = CarePatient(
        patient_id=validate_id(patient_id, "patient_id") if patient_id else new_id("pat"),
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        display_name=display_name,
        timezone=timezone,
        care_profile=profile,
        channels=list(channels or ["app"]),
        quiet_hours_start=quiet_hours[0] if quiet_hours else None,
        quiet_hours_end=quiet_hours[1] if quiet_hours else None,
    )
    session.add(patient)
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="artifact",
        subject_id=patient.patient_id,
        transition={"from": None, "to": "active", "reason": "patient created"},
        attributes={"record_type": "patient", "care_profile": profile},
    )
    return patient


async def get_patient(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, required_scope: str = "routine.read"
) -> CarePatient:
    """อ่านผู้ป่วยหนึ่งราย — ผ่าน tenant guard แล้วจึงตรวจ consent"""
    result = await session.execute(
        scoped(select(CarePatient).where(CarePatient.patient_id == patient_id), CarePatient, scope)
    )
    patient = result.scalar_one_or_none()
    if patient is None:
        raise PatientNotFound(f"ไม่พบผู้ป่วย {patient_id} ใน tenant {scope.tenant_id}")
    assert_same_tenant(scope, patient)
    await require_consent(session, scope, subject_id=patient_id, required_scope=required_scope)
    return patient


async def list_patients(session: AsyncSession, scope: TenantScope) -> list[CarePatient]:
    result = await session.execute(scoped(select(CarePatient), CarePatient, scope))
    return list(result.scalars())


def feature_enabled(patient: CarePatient, feature: str) -> bool:
    return bool((patient.care_profile or {}).get(feature, False))


@care_action("care.profile.update")
async def update_care_profile(
    session: AsyncSession, scope: TenantScope, patient_id: str, changes: dict
) -> CarePatient:
    patient = await get_patient(session, scope, patient_id, required_scope="care.manage")
    before = dict(patient.care_profile or {})
    profile = dict(before)
    for key, value in changes.items():
        if key not in DEFAULT_CARE_PROFILE:
            raise ValueError(f"care_profile ไม่รู้จักคีย์ '{key}'")
        profile[key] = bool(value)
    patient.care_profile = profile
    await session.flush()
    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="artifact",
        subject_id=patient.patient_id,
        transition={"from": "care_profile", "to": "care_profile", "reason": "profile updated"},
        attributes={"record_type": "patient", "before": before, "after": profile},
    )
    return patient


async def add_caregiver(
    session: AsyncSession,
    scope: TenantScope,
    *,
    principal_id: str,
    display_name: str,
    relation: str = "",
    channel: str = "app",
) -> CareCaregiver:
    caregiver = CareCaregiver(
        caregiver_id=new_id("cg"),
        tenant_id=scope.tenant_id,
        principal_id=validate_id(principal_id, "principal_id"),
        display_name=display_name,
        relation=relation,
        channel=channel,
    )
    session.add(caregiver)
    await session.flush()
    return caregiver


async def assign_to_care_team(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    caregiver_id: str,
    escalation_order: int = 1,
    is_emergency_contact: bool = False,
) -> CareTeamMember:
    member = CareTeamMember(
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        caregiver_id=caregiver_id,
        escalation_order=escalation_order,
        is_emergency_contact=is_emergency_contact,
    )
    session.add(member)
    await session.flush()
    return member


async def care_team(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, emergency_only: bool = False
) -> list[CareCaregiver]:
    """ทีมดูแลเรียงตามลำดับการ escalate — ไม่ส่งพร้อมกันทุกคน ยกเว้น critical"""
    stmt = (
        select(CareCaregiver, CareTeamMember)
        .join(CareTeamMember, CareTeamMember.caregiver_id == CareCaregiver.caregiver_id)
        .where(CareTeamMember.patient_id == patient_id)
        .order_by(CareTeamMember.escalation_order)
    )
    if emergency_only:
        stmt = stmt.where(CareTeamMember.is_emergency_contact.is_(True))
    result = await session.execute(scoped(stmt, CareTeamMember, scope))
    return [row[0] for row in result.all()]
