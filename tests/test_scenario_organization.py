"""Scenario S16, S17 — องค์กรภายนอก (M6 core)

    S16 หมอจาก รพ. A ได้สิทธิ์อ่านข้อมูล → อ่านได้ · หมอจาก รพ. B อ่านไม่ได้
    S17 หมอลาออกจาก รพ. A → เข้าไม่ได้ทันที **แม้ใบ consent จะยังไม่หมดอายุ**

🔒 [ADR-0010](../decisions/0010-organizations-are-not-tenants.md):
   องค์กรไม่ใช่ tenant · consent ให้แก่คน · สิทธิ์จริง = consent AND สมาชิกภาพที่ยัง active
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from core.clock import FakeClock, now
from core.tenancy import Principal, TenantScope

from care_addons.ap_consent import services as consent
from care_addons.care_medication import services as meds
from care_addons.care_organization import services as orgs
from tests.conftest import scope_for, setup_patient

ADMIN = Principal(type="human", id="user-1", display_name="ลูกสาว")
DOCTOR = Principal(type="human", id="user-doctor-a", display_name="หมอสมชาย")
AGENT = Principal(type="agent", id="care-agent")


def doctor_scope(tenant_id: str, principal_id: str = "user-doctor-a"):
    return TenantScope(
        tenant_id=tenant_id, principal=Principal(type="human", id=principal_id)
    )


async def _hospital_with_doctor(session, tenant_id, patient_id, *, expires_at=None):
    scope = scope_for(tenant_id)
    hospital = await orgs.add_organization(
        session, scope, name="โรงพยาบาล A", kind="hospital", contact="02-000-0000"
    )
    membership = await orgs.add_member(
        session, scope, hospital.organization_id,
        principal=DOCTOR, role="doctor", display_name="หมอสมชาย",
    )
    grant = await orgs.grant_clinical_access(
        session,
        scope,
        patient_id=patient_id,
        organization_id=hospital.organization_id,
        principal=DOCTOR,
        granted_by=ADMIN,
        authority_basis="ผู้ดูแลหลักอนุญาตให้แพทย์เจ้าของไข้ดูข้อมูล",
        expires_at=expires_at,
    )
    return hospital, membership, grant


async def test_s16_doctor_from_the_granted_organization_can_read(session, tenant):
    with FakeClock("2026-08-20T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        hospital, _, grant = await _hospital_with_doctor(session, tenant, patient.patient_id)
        await session.commit()

        assert grant.purpose == "clinical_care"
        assert "clinical.read" in grant.scopes
        assert grant.conditions == [
            {"kind": "org_membership", "organization_id": hospital.organization_id}
        ]

        # หมอเข้าถึงข้อมูลทางคลินิกได้
        assert await consent.has_consent(
            session, doctor_scope(tenant), subject_id=patient.patient_id,
            required_scope="clinical.read",
        )
        # แต่ไม่ได้สิทธิ์ของผู้ดูแลหลัก
        assert not await consent.has_consent(
            session, doctor_scope(tenant), subject_id=patient.patient_id,
            required_scope="care.manage",
        )


async def test_s17_leaving_the_organization_revokes_access_immediately(session, tenant):
    """🔒 ใบยินยอมยังไม่หมดอายุ แต่สิทธิ์หายทันทีที่ลาออก (ADR-0010 ข้อ 4)"""
    with FakeClock("2026-08-20T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        _, membership, grant = await _hospital_with_doctor(
            session, tenant, patient.patient_id, expires_at=now() + timedelta(days=365)
        )
        await session.commit()
        assert await consent.has_consent(
            session, doctor_scope(tenant), subject_id=patient.patient_id,
            required_scope="clinical.read",
        )

        await orgs.end_membership(
            session, scope_for(tenant), membership.membership_id, reason="ย้ายไปโรงพยาบาลอื่น"
        )
        await session.commit()

        assert not await consent.has_consent(
            session, doctor_scope(tenant), subject_id=patient.patient_id,
            required_scope="clinical.read",
        )
        # ใบยังอยู่และยังไม่ถูกเพิกถอน — สิ่งที่เปลี่ยนคือเงื่อนไข ไม่ใช่ตัวใบ
        await session.refresh(grant)
        assert grant.revoked_at is None
        assert grant.expires_at is not None


async def test_doctor_from_another_organization_cannot_read(session, tenant):
    with FakeClock("2026-08-20T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        await _hospital_with_doctor(session, tenant, patient.patient_id)
        scope = scope_for(tenant)
        other = await orgs.add_organization(session, scope, name="โรงพยาบาล B", kind="hospital")
        await orgs.add_member(
            session, scope, other.organization_id,
            principal=Principal(type="human", id="user-doctor-b"), role="doctor",
        )
        await session.commit()

        # เป็นหมอจริง อยู่องค์กรจริง แต่ครอบครัวไม่ได้ให้สิทธิ์ → เข้าไม่ได้
        assert not await consent.has_consent(
            session, doctor_scope(tenant, "user-doctor-b"),
            subject_id=patient.patient_id, required_scope="clinical.read",
        )


async def test_access_cannot_be_granted_to_a_non_member(session, tenant):
    with FakeClock("2026-08-20T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        hospital = await orgs.add_organization(session, scope, name="คลินิกใกล้บ้าน", kind="clinic")
        await session.commit()

        with pytest.raises(orgs.OrganizationRuleViolation, match="ไม่ได้เป็นสมาชิก"):
            await orgs.grant_clinical_access(
                session, scope, patient_id=patient.patient_id,
                organization_id=hospital.organization_id,
                principal=Principal(type="human", id="user-stranger"),
                granted_by=ADMIN, authority_basis="ผู้ดูแลหลัก",
            )
        await session.rollback()


async def test_clinical_grant_can_never_include_care_manage(session, tenant):
    """🔒 care.manage คือสิทธิ์ของผู้ดูแลหลัก ไม่ใช่ของผู้ให้การรักษา (ADR-0010 ข้อ 5)"""
    with FakeClock("2026-08-20T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        hospital = await orgs.add_organization(session, scope, name="โรงพยาบาล A", kind="hospital")
        await orgs.add_member(session, scope, hospital.organization_id, principal=DOCTOR)
        await session.commit()

        with pytest.raises(orgs.OrganizationRuleViolation, match="care.manage"):
            await orgs.grant_clinical_access(
                session, scope, patient_id=patient.patient_id,
                organization_id=hospital.organization_id, principal=DOCTOR,
                granted_by=ADMIN, authority_basis="ผู้ดูแลหลัก",
                scopes=["clinical.read", "care.manage"],
            )
        await session.rollback()


async def test_agent_cannot_open_access_or_add_members(session, tenant):
    """🔒 agent จดชื่อโรงพยาบาลได้ แต่เปิดสิทธิ์ให้ใครไม่ได้ (profile deny)"""
    from care_addons.ap_policy.engine import PolicyDenied

    with FakeClock("2026-08-20T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        hospital = await orgs.add_organization(session, scope, name="โรงพยาบาล A", kind="hospital")
        await session.commit()
        org_id = hospital.organization_id      # เก็บไว้ก่อน — หลัง rollback object จะ expire
        patient_id = patient.patient_id

        agent_scope = TenantScope(tenant_id=tenant, principal=AGENT)
        with pytest.raises(PolicyDenied, match="profile"):
            await orgs.add_member(session, agent_scope, org_id, principal=DOCTOR)
        await session.rollback()

        with pytest.raises(PolicyDenied, match="profile"):
            await orgs.grant_clinical_access(
                session, agent_scope, patient_id=patient_id, organization_id=org_id,
                principal=DOCTOR, granted_by=ADMIN, authority_basis="ผู้ดูแลหลัก",
            )
        await session.rollback()


async def test_an_organization_is_not_a_tenant(session, tenant):
    """องค์กรของครอบครัวหนึ่ง ไม่โผล่ในอีกครอบครัวหนึ่ง — และไม่ใช่ tenant ของตัวเอง"""
    from addons.tenancy import services as kernel_tenancy

    from tests.conftest import use_tenant

    with FakeClock("2026-08-20T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        await _hospital_with_doctor(session, tenant, patient.patient_id)
        await session.commit()

        other = f"{tenant}-other"
        await kernel_tenancy.create_tenant(session, other, "อีกครอบครัว")
        await session.commit()
        await use_tenant(session, other)
        other_scope = TenantScope(tenant_id=other, principal=ADMIN)
        assert await orgs.organizations(session, other_scope) == []
        await use_tenant(session, tenant)


async def test_external_prescription_must_say_which_organization(session, tenant):
    """🔒 'hospital_document' ที่ไม่บอกว่าโรงพยาบาลไหน = คำที่ใครพิมพ์ก็ได้ (ADR-0010 ข้อ 7)"""
    with FakeClock("2026-08-20T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        hospital = await orgs.add_organization(session, scope, name="โรงพยาบาล A", kind="hospital")
        await session.commit()
        org_id = hospital.organization_id      # เก็บไว้ก่อน — หลัง rollback object จะ expire
        patient_id = patient.patient_id

        with pytest.raises(meds.MedicationRuleViolation, match="source_organization_id"):
            await meds.propose_version(
                session, scope, patient_id=patient_id, name="Med X",
                schedule=[{"time": "08:00", "relation_to_meal": "after_meal", "dose": "1 เม็ด"}],
                instruction_source="hospital_document",
            )
        await session.rollback()

        version = await meds.propose_version(
            session, scope, patient_id=patient_id, name="Med X",
            schedule=[{"time": "08:00", "relation_to_meal": "after_meal", "dose": "1 เม็ด"}],
            instruction_source="hospital_document",
            source_organization_id=org_id,
            source_document_ref="ใบสั่งยาเลขที่ 2026/0819",
        )
        await session.commit()
        # 🔒 มาจากโรงพยาบาลจริงก็ยังเป็นแค่ข้อเสนอ — ไม่มี trusted source ที่ข้ามคนได้
        assert version.status == "proposed"
        assert version.source_organization_id == org_id


async def test_open_access_shows_who_can_read_right_now(session, tenant):
    with FakeClock("2026-08-20T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        _, membership, _ = await _hospital_with_doctor(session, tenant, patient.patient_id)
        await session.commit()

        scope = scope_for(tenant)
        rows = await orgs.open_access(session, scope, patient.patient_id)
        clinical = [r for r in rows if r["organization_id"]]
        assert len(clinical) == 1
        assert clinical[0]["grantee_id"] == "user-doctor-a"
        assert clinical[0]["conditions_hold"] is True

        await orgs.end_membership(
            session, scope, membership.membership_id, reason="ลาออก"
        )
        await session.commit()

        rows = await orgs.open_access(session, scope, patient.patient_id)
        clinical = [r for r in rows if r["organization_id"]]
        # ใบยังอยู่ในรายการ แต่บอกชัดว่าเงื่อนไขไม่เป็นจริงแล้ว — ผู้ดูแลจะได้ไปเก็บกวาด
        assert clinical[0]["conditions_hold"] is False


async def test_unknown_condition_kind_fails_closed(session, tenant):
    """เงื่อนไขที่ไม่มีใครตรวจได้ = ไม่อนุญาต (หลักเดียวกับ scope ที่ไม่รู้จักใน consent/v1)"""
    with FakeClock("2026-08-20T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)

        with pytest.raises(ValueError, match="ไม่มีตัวตรวจ"):
            await consent.grant_consent(
                session, scope, subject_id=patient.patient_id,
                grantee=DOCTOR, scopes=["clinical.read"], purpose="clinical_care",
                granted_by=ADMIN, authority_basis="ผู้ดูแลหลัก",
                conditions=[{"kind": "phase_of_the_moon"}],
            )
        await session.rollback()


async def test_membership_must_be_a_person(session, tenant):
    with FakeClock("2026-08-20T01:00:00+00:00"):
        await setup_patient(session, tenant)
        scope = scope_for(tenant)
        hospital = await orgs.add_organization(session, scope, name="ร้านยาใกล้บ้าน", kind="pharmacy")
        await session.commit()

        with pytest.raises(orgs.OrganizationRuleViolation, match="ต้องเป็นคน"):
            await orgs.add_member(
                session, scope, hospital.organization_id,
                principal=Principal(type="service", id="pharmacy-bot"),
            )
        await session.rollback()


async def test_daily_summary_shows_stale_clinical_access(session, tenant):
    """ใบยินยอมที่เงื่อนไขตายแล้วต้องโผล่ในสรุป ไม่งั้นมันค้างอยู่โดยไม่มีใครเก็บกวาด"""
    from care_addons.care_orchestrator import services as orchestrator
    from tests.conftest import system_scope

    with FakeClock("2026-08-20T13:05:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        _, membership, _ = await _hospital_with_doctor(session, tenant, patient.patient_id)
        await session.commit()

        row = await orchestrator.send_daily_summary(session, system_scope(tenant), patient)
        await session.commit()
        assert len(row.facts["clinical_access"]) == 1
        assert "ผู้ให้การรักษาที่เข้าถึงข้อมูลได้ 1 ราย" in row.text
        assert "ควรเพิกถอน" not in row.text

        await orgs.end_membership(
            session, scope_for(tenant), membership.membership_id, reason="ลาออก"
        )
        await session.commit()

        tomorrow = await orchestrator.send_daily_summary(
            session, system_scope(tenant), patient, force=True
        )
        await session.commit()
        assert "ควรเพิกถอน" in tomorrow.text
