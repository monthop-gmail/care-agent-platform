"""Scenario S7, S8 + กติกาที่ platform layer ต้องบังคับได้จริง

    S7  ถาม "กินยาแล้วยัง" โดยไม่มีหลักฐาน → ตอบว่าไม่มีข้อมูล (ห้ามเดา)
    S8  caregiver ของ tenant อื่นพยายามอ่าน → ถูกปฏิเสธที่ชั้น tenancy
"""

from __future__ import annotations

import pytest
from addons.tenancy import services as kernel_tenancy
from core.clock import FakeClock
from core.tenancy import InvalidId, Principal, TenantScope, validate_id

from care_addons.ap_audit import services as audit
from care_addons.ap_consent import services as consent
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
        await kernel_tenancy.create_tenant(session, "t-family-a", "ครอบครัว A")
        await kernel_tenancy.create_tenant(session, "t-family-b", "ครอบครัว B")
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
        with pytest.raises(consent.ConsentDenied):
            await patients.get_patient(session, stranger, patient.patient_id)

        await consent.grant_consent(
            session,
            scope_for(tenant),
            subject_id=patient.patient_id,
            grantee=Principal(type="human", id="user-7"),
            scopes=["routine.read"],
            granted_by=Principal(type="human", id="user-1"),
            authority_basis="ผู้ดูแลหลักที่ครอบครัวมอบหมาย",
        )
        await session.commit()

        assert await patients.get_patient(session, stranger, patient.patient_id)

        # ได้เฉพาะ scope ที่ให้ — ข้อมูลยายังต้องขอแยก
        with pytest.raises(consent.ConsentDenied):
            await patients.get_patient(
                session, stranger, patient.patient_id, required_scope="medication.read"
            )


async def test_revoked_consent_takes_effect_immediately(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant, with_caregiver=False)
        admin = scope_for(tenant)
        grant = await consent.grant_consent(
            session,
            admin,
            subject_id=patient.patient_id,
            grantee=Principal(type="human", id="user-8"),
            scopes=["routine.read"],
            granted_by=Principal(type="human", id="user-1"),
            authority_basis="ผู้ดูแลหลักที่ครอบครัวมอบหมาย",
        )
        await session.commit()

        viewer = scope_for(tenant, "user-8")
        assert await patients.get_patient(session, viewer, patient.patient_id)

        await consent.revoke_consent(
            session, admin, grant.grant_id, reason="ครอบครัวขอถอนสิทธิ์หลังเปลี่ยนผู้ดูแล"
        )
        await session.commit()

        with pytest.raises(consent.ConsentDenied):
            await patients.get_patient(session, viewer, patient.patient_id)


async def test_audit_rejects_events_it_cannot_ground(session, tenant):
    """event/v1 invariants — reject ที่ intake ห้ามเดาให้"""
    scope = scope_for(tenant)

    with pytest.raises(audit.EventRejected, match="tenant"):
        await audit.emit(
            session,
            TenantScope(tenant_id="", principal=scope.principal),
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


# ── เพดานของ agent profile (profile/v1) ──────────────────────────────────────
#
# ก่อนหน้านี้ `profiles/care-agent/profile.yaml` ไม่มีโค้ดไหนอ่านเลย — เอกสารที่ดูเหมือน
# กติกาแต่ไม่มีผล ซึ่งอันตรายกว่าไม่มีไฟล์นั้น เพราะคนอ่านแล้วเชื่อว่าระบบกันให้อยู่

def test_profile_denies_capabilities_for_agents_no_matter_what_policy_says():
    """🔒 deny ชนะ allow และชนะ authority_map — ต่อให้ policy ของ tenant เผลอเปิด"""
    from care_addons.ap_policy.engine import evaluate

    for capability in ("medication.regimen.write", "careplan.task.activate", "care.profile.update"):
        agent_view = evaluate(capability, actor_type="agent")
        assert agent_view.profile_denied is True, capability
        assert agent_view.effect == "deny"
        assert agent_view.may_act_now is False

        # คนไม่ได้อยู่ใต้ profile ของ agent — ผู้ดูแลที่ยืนยันคำสั่งยาใช้อำนาจของคน
        human_view = evaluate(capability, actor_type="human")
        assert human_view.profile_denied is False, capability


def test_capability_outside_the_allowlist_is_denied_for_agents():
    """allow ว่าง/ไม่ครอบ = ไม่อนุญาต ไม่ใช่ 'อนุญาตทั้งหมด' (profile/v1)"""
    from care_addons.ap_policy.engine import evaluate

    denied = evaluate("appointment.write", actor_type="agent")
    assert denied.profile_denied is True
    assert "allowlist" in denied.reason

    allowed = evaluate("medication.regimen.propose", actor_type="agent")
    assert allowed.profile_denied is False
    assert allowed.may_act_now is True


async def test_agent_cannot_call_a_denied_action_even_when_it_needs_a_human_anyway(session, tenant):
    """autonomous=False แปลว่า 'ต้องมีคนเกี่ยวข้อง' ไม่ใช่ 'ใครเรียกก็ได้'"""
    from care_addons.ap_policy.engine import PolicyDenied
    from care_addons.care_careplan import services as careplan

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        agent_scope = TenantScope(
            tenant_id=tenant, principal=Principal(type="agent", id="care-agent")
        )
        await consent.grant_consent(
            session,
            scope_for(tenant),
            subject_id=patient.patient_id,
            grantee=Principal(type="agent", id="care-agent"),
            scopes=["care.manage"],
            granted_by=Principal(type="human", id="user-1"),
            authority_basis="ผู้ดูแลหลักมอบหมาย",
        )
        task = await careplan.propose_task(
            session,
            scope_for(tenant),
            patient_id=patient.patient_id,
            task_type="exercise",
            description="เดินวันละ 20 นาที",
            frequency={"type": "daily"},
            source={"kind": "doctor_visit"},
        )
        await session.commit()

        with pytest.raises(PolicyDenied, match="profile"):
            await careplan.activate_task(
                session,
                agent_scope,
                task.task_id,
                activated_by=Principal(type="human", id="user-1"),
            )
        await session.rollback()


def test_tenant_policy_cannot_be_looser_than_the_profile_ceiling(tmp_path):
    """profile เป็นเพดาน — config ที่หลวมกว่าต้องทำให้ boot ไม่ผ่าน ไม่ใช่ทำงานต่อเงียบ ๆ"""
    from care_addons.ap_policy.engine import PolicyConfigError, load_policy

    loose = tmp_path / "loose-authority-map.yaml"
    loose.write_text(
        "policy_id: test.loose.v1\n"
        "authority_map:\n"
        "  low: auto\n"
        "  medium: notify\n"
        "  high: notify\n"            # profile บอกว่า high ต้อง approval_required
        "  critical: human_command_required\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyConfigError, match="เพดานของ profile"):
        load_policy(str(loose))


def test_emergency_escalation_stays_fast_under_the_ceiling():
    """ข้อยกเว้นที่ประกาศไว้และ audit เต็ม ไม่ถูกเพดานยกทับ (ADR-0007 ข้อ 5)

    ถ้าเพดานยกทับ emergency.escalate จะกลายเป็น human_command_required
    ซึ่งแปลว่าตอนฉุกเฉินระบบจะรอคนสั่งก่อนถึงจะเรียกคน — ตรงข้ามกับที่ต้องการ
    """
    from care_addons.ap_policy.engine import evaluate

    decision = evaluate("emergency.escalate")
    assert decision.action_risk == "critical"
    assert decision.authority == "notify"
    assert decision.audited_exception is True
    assert decision.may_act_now is True
