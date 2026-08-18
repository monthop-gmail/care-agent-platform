"""Scenario S7, S8 + กติกาที่ platform layer ต้องบังคับได้จริง

    S7  ถาม "กินยาแล้วยัง" โดยไม่มีหลักฐาน → ตอบว่าไม่มีข้อมูล (ห้ามเดา)
    S8  caregiver ของ tenant อื่นพยายามอ่าน → ถูกปฏิเสธที่ชั้น tenancy
"""

from __future__ import annotations

import pytest

from care_addons.ap_audit import services as audit
from care_addons.ap_tenancy import services as tenancy
from care_addons.ap_tenancy.clock import FakeClock
from care_addons.ap_tenancy.ids import InvalidId, validate_id
from care_addons.care_patient import services as patients
from care_addons.care_routine import services as routines
from tests.conftest import scope_for, setup_patient, system_scope


async def test_s7_no_evidence_means_no_data(session, tenant):
    """ยังไม่ยืนยัน = ยังไม่มีข้อมูล — ห้ามอนุมานว่าทำแล้วเพราะเวลาผ่านไป"""
    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant)
        admin = scope_for(tenant)
        await routines.add_routine(
            session,
            admin,
            patient_id=patient.patient_id,
            kind="meal",
            label="อาหารเช้า",
            scheduled_time="07:30",
        )
        await session.commit()

        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        clock.set("2026-08-19T05:00:00+00:00")   # เที่ยงตามเวลาไทย — ผ่านมื้อเช้ามานาน
        plan = await routines.today_plan(session, admin, patient.patient_id)
        breakfast = next(item for item in plan if item["label"] == "อาหารเช้า")

        assert breakfast["confirmed"] is False
        assert breakfast["state"] in ("pending", "reminded", "missed", "escalated")


async def test_s8_cross_tenant_read_is_blocked(session):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        await tenancy.create_tenant(session, "t-family-a", "ครอบครัว A")
        await tenancy.create_tenant(session, "t-family-b", "ครอบครัว B")
        await session.commit()

        patient_a, _ = await setup_patient(session, "t-family-a", with_caregiver=False)

        # คนของอีก tenant มี consent ในบ้านตัวเอง แต่ยังเห็นผู้ป่วยของบ้าน A ไม่ได้
        intruder = scope_for("t-family-b", "user-9")
        with pytest.raises(patients.PatientNotFound):
            await patients.get_patient(session, intruder, patient_a.patient_id)

        assert await patients.list_patients(session, intruder) == []


async def test_consent_is_required_even_inside_the_same_tenant(session, tenant):
    """ADR-0007: RBAC ผ่านอย่างเดียวไม่พอ — ต้องมี consent กับผู้ป่วยรายนั้นด้วย"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant, with_caregiver=False)

        stranger = scope_for(tenant, "user-7")
        with pytest.raises(tenancy.ConsentDenied):
            await patients.get_patient(session, stranger, patient.patient_id)

        await tenancy.grant_consent(
            session,
            scope_for(tenant),
            subject_id=patient.patient_id,
            grantee=tenancy.Principal(type="human", id="user-7"),
            scopes=["routine.read"],
            granted_by=tenancy.Principal(type="human", id="user-1"),
        )
        await session.commit()

        assert await patients.get_patient(session, stranger, patient.patient_id)

        # ได้เฉพาะ scope ที่ให้ — ข้อมูลยายังต้องขอแยก
        with pytest.raises(tenancy.ConsentDenied):
            await patients.get_patient(
                session, stranger, patient.patient_id, required_scope="medication.read"
            )


async def test_revoked_consent_takes_effect_immediately(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant, with_caregiver=False)
        admin = scope_for(tenant)
        grant = await tenancy.grant_consent(
            session,
            admin,
            subject_id=patient.patient_id,
            grantee=tenancy.Principal(type="human", id="user-8"),
            scopes=["routine.read"],
            granted_by=tenancy.Principal(type="human", id="user-1"),
        )
        await session.commit()

        viewer = scope_for(tenant, "user-8")
        assert await patients.get_patient(session, viewer, patient.patient_id)

        await tenancy.revoke_consent(session, admin, grant.grant_id)
        await session.commit()

        with pytest.raises(tenancy.ConsentDenied):
            await patients.get_patient(session, viewer, patient.patient_id)


async def test_audit_rejects_events_it_cannot_ground(session, tenant):
    """event/v1 invariants — reject ที่ intake ห้ามเดาให้"""
    scope = scope_for(tenant)

    with pytest.raises(audit.EventRejected, match="tenant"):
        await audit.emit(
            session,
            tenancy.TenantScope(tenant_id="", principal=scope.principal),
            event_type="JOB_CREATED",
            subject_type="job",
            subject_id="job-1",
        )

    with pytest.raises(audit.EventRejected, match="event/v1"):
        await audit.emit(
            session, scope, event_type="SOMETHING_NEW", subject_type="job", subject_id="job-1"
        )

    with pytest.raises(audit.EventRejected, match="source_system"):
        await audit.emit(
            session,
            scope,
            event_type="STATE_TRANSITION",
            subject_type="external",
            subject_id="dev-1",
            source_kind="external",
        )

    with pytest.raises(audit.EventRejected, match="chain-of-thought"):
        await audit.emit(
            session,
            scope,
            event_type="STATE_TRANSITION",
            subject_type="job",
            subject_id="job-1",
            attributes={"reasoning": "ผู้ป่วยน่าจะลืมเพราะ..."},
        )


async def test_ids_follow_platform_pattern(session):
    for good in ["t-family-a", "pat-abc123", "user-1"]:
        assert validate_id(good) == good
    for bad in ["Family_A", "-leading", "ผู้ป่วย", "x" * 64]:
        with pytest.raises(InvalidId):
            validate_id(bad)


async def test_quiet_hours_defer_reminders(session, tenant):
    """ช่วงห้ามรบกวนมีผลกับ severity ต่ำกว่า critical — เลื่อน ไม่ใช่ข้าม"""
    from care_addons.care_escalation import services as jobs

    with FakeClock("2026-08-18T17:00:00+00:00") as clock:   # เที่ยงคืนตามเวลาไทย
        patient, _ = await setup_patient(session, tenant, quiet_hours=("21:00", "06:00"))
        admin = scope_for(tenant)
        await routines.add_routine(
            session,
            admin,
            patient_id=patient.patient_id,
            kind="medication",
            label="ยาก่อนนอน",
            scheduled_time="00:00",
        )
        await session.commit()

        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        summary = await jobs.run_due_jobs(session, sysscope)
        await session.commit()
        assert summary["deferred"] == 1
        assert summary["reminded"] == 0

        job = (await jobs.open_jobs(session, sysscope, patient.patient_id))[0]
        assert job.attempts == 0
        assert job.next_attempt_at is not None

        clock.set("2026-08-18T23:30:00+00:00")   # 06:30 ตามเวลาไทย — พ้นช่วงห้ามรบกวน
        summary = await jobs.run_due_jobs(session, sysscope)
        await session.commit()
        assert summary["reminded"] == 1
