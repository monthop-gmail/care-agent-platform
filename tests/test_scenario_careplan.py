"""Scenario S13 — คำสั่งหลังพบหมอกลายเป็นงานที่เกิดขึ้นจริง

    หมอบอกในห้องตรวจ 30 วินาที: "เดินวันละ 20 นาที ดื่มน้ำเพิ่ม ทายาที่เข่าเช้า-เย็น งดอาหารเค็ม"
    ผู้ป่วยความจำถดถอยลืมภายในวันเดียว — โมดูลนี้ทำให้มันมีเวลา มีการยืนยัน และตรวจย้อนได้

🔒 กติกาที่เทสในไฟล์นี้บังคับ (contracts/careplan/v1):
   AI จดได้แค่ proposed · คนเท่านั้นที่ทำให้มีผล · ไม่มีบันทึก = บอกว่าข้อมูลไม่พอ ไม่ใช่ 0%
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from core.clock import FakeClock
from core.tenancy import Principal, TenantScope

from care_addons.ap_approval import services as approvals
from care_addons.care_careplan import services as careplan
from care_addons.care_escalation import services as jobs
from care_addons.care_orchestrator import services as orchestrator
from tests.conftest import scope_for, setup_patient, system_scope

DAY = date(2026, 8, 19)
DOCTOR_VISIT = {"kind": "doctor_visit", "confirmed_by": {"type": "human", "id": "user-1"}}
DAUGHTER = {"type": "human", "id": "user-daughter", "display_name": "ลูกสาว"}
AGENT = Principal(type="agent", id="care-agent")


async def _propose_walk(session, tenant_id, patient_id, **overrides):
    payload = dict(
        patient_id=patient_id,
        task_type="exercise",
        description="เดินรอบบ้านหลังอาหารเย็น",
        frequency={"type": "daily"},
        source=DOCTOR_VISIT,
        scheduled_times=["17:30"],
        duration_minutes=20,
        start_date=DAY,
    )
    payload.update(overrides)
    return await careplan.propose_task(session, scope_for(tenant_id), **payload)


async def test_doctor_instruction_starts_as_proposed_and_waits_for_a_human(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        task = await _propose_walk(session, tenant, patient.patient_id)
        await session.commit()

        assert task.status == "proposed"
        assert task.source["kind"] == "doctor_visit"
        assert task.duration_minutes == 20

        # ยังไม่มีผล = ยังไม่มีงานให้ผู้ป่วยทำ
        sysscope = system_scope(tenant)
        assert await careplan.materialize_day(session, sysscope, patient.patient_id, for_date=DAY) == []

        # และมีคำขอรออยู่ในคิวของผู้ดูแล
        [request] = await approvals.pending_requests(session, scope_for(tenant))
        assert request.subject_id == task.task_id
        assert request.capability == "careplan.task.activate"
        assert request.authority_required == "approval_required"


async def test_approving_makes_the_instruction_real(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        task = await _propose_walk(session, tenant, patient.patient_id)
        await session.commit()

        scope = scope_for(tenant)
        [request] = await approvals.pending_requests(session, scope)
        await approvals.decide(
            session,
            scope,
            request_id=request.request_id,
            decision="APPROVE",
            reason="หมอสั่งไว้จริงตามใบนัด",
            authority=DAUGHTER,
        )
        await session.commit()

        await session.refresh(task)
        assert task.status == "active"
        assert task.activated_by["id"] == "user-daughter"   # ชื่อคนที่ตัดสิน ไม่ใช่ agent

        sysscope = system_scope(tenant)
        created = await careplan.materialize_day(session, sysscope, patient.patient_id, for_date=DAY)
        await session.commit()
        assert len(created) == 1
        assert created[0].source_kind == "careplan"
        assert created[0].label == "เดินรอบบ้านหลังอาหารเย็น (20 นาที)"
        # 17:30 ตามเวลาไทย = 10:30 UTC
        assert created[0].due_at.strftime("%H:%M") == "10:30"

        # เรียกซ้ำต้องไม่สร้างงานซ้ำ
        assert await careplan.materialize_day(session, sysscope, patient.patient_id, for_date=DAY) == []


async def test_agent_cannot_activate_an_instruction(session, tenant):
    """AI จดได้ แต่ทำให้คำสั่งของหมอมีผลไม่ได้ (careplan/v1 กติกาข้อ 1)"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        task = await _propose_walk(session, tenant, patient.patient_id)
        await session.commit()

        with pytest.raises(careplan.CarePlanRuleViolation, match="ต้องเป็นคน"):
            await careplan.activate_task(
                session, scope_for(tenant), task.task_id, activated_by=AGENT
            )
        await session.rollback()
        await session.refresh(task)
        assert task.status == "proposed"


async def test_a_standing_restriction_never_becomes_a_reminder(session, tenant):
    """"งดอาหารเค็ม" ไม่มีเวลาให้ทำเสร็จ — เตือนทุกวันคือเสียงรบกวน ไม่ใช่การดูแล"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        task = await _propose_walk(
            session,
            tenant,
            patient.patient_id,
            task_type="restriction",
            description="งดอาหารเค็ม",
            frequency={"type": "ongoing"},
            scheduled_times=None,
            duration_minutes=None,
        )
        await careplan.activate_task(
            session,
            scope_for(tenant),
            task.task_id,
            activated_by=Principal(type="human", id="user-1"),
        )
        await session.commit()

        assert task.status == "active"
        assert task.scheduled_times == []
        assert task.reminders_enabled is False
        sysscope = system_scope(tenant)
        assert await careplan.materialize_day(session, sysscope, patient.patient_id, for_date=DAY) == []


async def test_times_per_day_without_explicit_times_gets_spread_out(session, tenant):
    """จำนวนครั้งเป็นคำสั่งของหมอ · เวลาเป็นความสะดวกของครอบครัว — เดาได้เฉพาะอย่างหลัง"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        task = await _propose_walk(
            session,
            tenant,
            patient.patient_id,
            task_type="hydration",
            description="ดื่มน้ำ 1 แก้ว",
            frequency={"type": "times_per_day", "times": 3},
            scheduled_times=None,
            duration_minutes=None,
        )
        await session.commit()
        assert task.frequency == {"type": "times_per_day", "times": 3}
        assert len(task.scheduled_times) == 3
        assert len(set(task.scheduled_times)) == 3     # ไม่ซ้ำเวลากันเอง

        with pytest.raises(ValueError, match="frequency.times"):
            await careplan.propose_task(
                session,
                scope_for(tenant),
                patient_id=patient.patient_id,
                task_type="hydration",
                description="ดื่มน้ำ",
                frequency={"type": "times_per_day"},   # บอกว่าหลายครั้ง แต่ไม่บอกกี่ครั้ง
                source=DOCTOR_VISIT,
            )
        await session.rollback()


async def test_instruction_stops_after_its_end_date(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        task = await _propose_walk(
            session, tenant, patient.patient_id, end_date=DAY + timedelta(days=2)
        )
        await careplan.activate_task(
            session, scope_for(tenant), task.task_id,
            activated_by=Principal(type="human", id="user-1"),
        )
        await session.commit()

        sysscope = system_scope(tenant)
        assert len(await careplan.materialize_day(
            session, sysscope, patient.patient_id, for_date=DAY + timedelta(days=2)
        )) == 1
        assert await careplan.materialize_day(
            session, sysscope, patient.patient_id, for_date=DAY + timedelta(days=3)
        ) == []


async def test_adherence_says_no_data_instead_of_zero_percent(session, tenant):
    """0% อ่านเหมือน "ไม่ได้ทำเลย" · "ไม่มีข้อมูล" ทำให้ผู้ดูแลไปหาข้อมูลต่อ (careplan/v1 ข้อ 2)"""
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant)
        task = await _propose_walk(session, tenant, patient.patient_id)
        await careplan.activate_task(
            session, scope_for(tenant), task.task_id,
            activated_by=Principal(type="human", id="user-1"),
        )
        await session.commit()

        scope = scope_for(tenant)
        empty = await careplan.adherence(session, scope, task.task_id)
        assert empty["available"] is False
        assert "ข้อมูลไม่พอ" in empty["reason"]

        sysscope = system_scope(tenant)
        created = await careplan.materialize_day(session, sysscope, patient.patient_id, for_date=DAY)
        await session.commit()

        clock.set("2026-08-19T10:35:00+00:00")      # 17:35 ไทย — เลยเวลาเดินแล้ว
        await jobs.run_due_jobs(session, sysscope)
        await jobs.acknowledge(
            session, scope_for(tenant, patient.patient_id), created[0].care_job_id
        )
        await session.commit()

        report = await careplan.adherence(session, scope, task.task_id)
        assert report["available"] is True
        assert report["due"] == 1
        assert report["confirmed"] == 1
        assert "ไม่ได้ยืนยันไม่ได้แปลว่าไม่ได้ทำ" in report["note"]


async def test_paused_instruction_creates_no_new_jobs(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        task = await _propose_walk(session, tenant, patient.patient_id)
        scope = scope_for(tenant)
        await careplan.activate_task(
            session, scope, task.task_id, activated_by=Principal(type="human", id="user-1")
        )
        await careplan.set_status(
            session, scope, task.task_id, status="paused", reason="ปวดเข่า หมอให้พักก่อน"
        )
        await session.commit()

        assert task.status == "paused"
        sysscope = system_scope(tenant)
        assert await careplan.materialize_day(session, sysscope, patient.patient_id, for_date=DAY) == []

        with pytest.raises(careplan.CarePlanRuleViolation, match="activate_task"):
            await careplan.set_status(
                session, scope, task.task_id, status="active", reason="กลับมาเดินต่อ"
            )
        await session.rollback()


async def test_orchestrator_creates_the_days_work_without_anyone_asking(session, tenant):
    """closed loop ต้องไม่ขึ้นกับว่ามีใครจำได้ว่าต้องยิง /materialize"""
    from care_addons.care_routine import services as routines

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        await routines.add_routine(
            session, scope, patient_id=patient.patient_id, kind="medication",
            label="ยาเช้า หลังอาหาร", scheduled_time="08:00",
        )
        task = await _propose_walk(session, tenant, patient.patient_id)
        await careplan.activate_task(
            session, scope, task.task_id, activated_by=Principal(type="human", id="user-1")
        )
        await session.commit()

        sysscope = system_scope(tenant)
        result = await orchestrator.run_cycle(session, sysscope)
        await session.commit()
        assert result["routine_jobs"] == 1
        assert result["careplan_jobs"] == 1
        assert result["skipped_no_consent"] == 0

        # เรียกซ้ำในวันเดียวกันต้องไม่สร้างงานซ้ำ
        again = await orchestrator.run_cycle(session, sysscope)
        await session.commit()
        assert again["routine_jobs"] == 0
        assert again["careplan_jobs"] == 0


async def test_patient_without_consent_is_skipped_not_crashed(session, tenant):
    """ไม่มี consent = ไม่แตะข้อมูลคนนั้น — แต่ต้องไม่ทำให้ผู้ป่วยคนอื่นใน tenant หยุดตาม"""
    from care_addons.care_patient import services as patients
    from care_addons.care_routine import services as routines

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        await routines.add_routine(
            session, scope, patient_id=patient.patient_id, kind="meal",
            label="อาหารเช้า", scheduled_time="07:30",
        )
        stranger = await patients.create_patient(
            session, scope, display_name="คุณปู่", timezone="Asia/Bangkok",
            care_profile={"routine": True}, channels=["line"],
        )
        await session.commit()
        assert stranger.patient_id      # ไม่มี consent ให้ orchestrator

        result = await orchestrator.run_cycle(session, system_scope(tenant))
        await session.commit()
        assert result["routine_jobs"] == 1
        assert result["skipped_no_consent"] == 1


async def test_careplan_tasks_do_not_leak_across_tenants(session, tenant):
    from addons.tenancy import services as kernel_tenancy

    from tests.conftest import use_tenant

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        await _propose_walk(session, tenant, patient.patient_id)
        await session.commit()

        other = f"{tenant}-other"
        await kernel_tenancy.create_tenant(session, other, "อีกครอบครัว")
        await session.commit()
        await use_tenant(session, other)
        other_scope = TenantScope(
            tenant_id=other, principal=Principal(type="human", id="user-1")
        )
        assert await careplan.list_tasks(session, other_scope, patient.patient_id) == []
        await use_tenant(session, tenant)


async def test_pausing_an_instruction_cancels_the_work_already_created_for_today(session, tenant):
    """🔒 หยุดคำสั่งต้องหยุดสิ่งที่ค้างอยู่ด้วย ไม่ใช่แค่หยุดสร้างใหม่

    งานของวันนี้ถูกสร้างไว้ตอนเช้าแล้ว — ถ้าไม่ยกเลิก ผู้ป่วยจะยังถูกเตือนให้เดิน
    ทั้งที่หมอสั่งให้พักเพราะปวดเข่า
    """
    from care_addons.care_escalation import services as jobs

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        task = await _propose_walk(session, tenant, patient.patient_id)
        await careplan.activate_task(
            session, scope, task.task_id, activated_by=Principal(type="human", id="user-1")
        )
        sysscope = system_scope(tenant)
        created = await careplan.materialize_day(
            session, sysscope, patient.patient_id, for_date=DAY
        )
        await session.commit()
        assert len(created) == 1

        await careplan.set_status(
            session, scope, task.task_id, status="paused", reason="ปวดเข่า หมอให้พักก่อน"
        )
        await session.commit()

        open_now = await jobs.open_jobs(session, sysscope, patient.patient_id)
        assert [j.state for j in open_now] == ["cancelled"]
        assert open_now[0].closed_at is not None
        assert open_now[0].next_attempt_at is None

        # ใบปิดท้ายบอกเหตุผลไว้ — ไม่ใช่หายไปเงียบ ๆ
        from care_addons.ap_audit import services as audit

        trail = await audit.trail(session, sysscope, created[0].correlation_id)
        settled = [e for e in trail if e.event_type == "JOB_SETTLED"]
        assert [e.attributes["settled_as"] for e in settled] == ["cancelled"]
        assert "ปวดเข่า" in settled[0].attributes["reason"]
        assert "JOB_COMPLETED" not in [e.event_type for e in trail]
