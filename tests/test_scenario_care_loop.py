"""Scenario S1, S2 — closed loop ของการเตือน

จาก architecture/team-plan.md:
    S1  ผู้ป่วยยืนยันกินยา  → confirmed ไม่มี escalation
    S2  ผู้ป่วยเงียบ        → retry → missed → caregiver ถูกแจ้ง
"""

from __future__ import annotations

from core.clock import FakeClock

from care_addons.ap_audit import services as audit
from care_addons.care_escalation import services as jobs
from care_addons.care_routine import services as routines
from tests.conftest import (
    audit_events,
    notifications,
    scope_for,
    setup_patient,
    system_scope,
)


async def _seed_morning_medication(session, tenant_id):
    patient, caregiver = await setup_patient(session, tenant_id)
    admin = scope_for(tenant_id)
    await routines.add_routine(
        session,
        admin,
        patient_id=patient.patient_id,
        kind="medication",
        label="ยาเช้า หลังอาหาร",
        scheduled_time="08:00",
        severity="medium",
    )
    await session.commit()
    return patient, caregiver


async def test_s1_patient_confirms(session, tenant):
    with FakeClock("2026-08-19T00:30:00+00:00"):   # 07:30 ตามเวลาไทย
        patient, _ = await _seed_morning_medication(session, tenant)
        sysscope = system_scope(tenant)

        created = await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()
        assert len(created) == 1
        job = created[0]
        assert job.state == "pending"


async def test_s1_confirm_closes_loop_without_escalation(session, tenant):
    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient, _ = await _seed_morning_medication(session, tenant)
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        clock.set("2026-08-19T01:00:00+00:00")     # 08:00 — ถึงเวลา
        summary = await jobs.run_due_jobs(session, sysscope)
        await session.commit()
        assert summary["reminded"] == 1

        open_jobs = await jobs.open_jobs(session, sysscope, patient.patient_id)
        job = open_jobs[0]
        assert job.state == "reminded"
        assert job.attempts == 1

        clock.advance(minutes=3)
        patient_scope = scope_for(tenant, patient.patient_id)
        confirmed = await jobs.acknowledge(session, patient_scope, job.care_job_id)
        await session.commit()

        assert confirmed.state == "confirmed"
        assert confirmed.evidence["kind"] == "patient_confirmed"

        # ไม่มีการแจ้ง caregiver เลย
        assert await notifications(session, tenant, patient.patient_id, "caregiver") == []

        # trail ตอบได้ว่าเกิดอะไรขึ้นบ้าง
        trail = await audit.trail(session, sysscope, job.correlation_id)
        kinds = [e.event_type for e in trail]
        assert kinds[0] == "JOB_CREATED"
        assert "EXECUTION_STARTED" in kinds
        assert kinds[-1] == "JOB_COMPLETED"
        assert "care.medication.confirmed" in [e.care_event_type for e in trail]


async def test_s2_silence_escalates_to_caregiver(session, tenant):
    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient, caregiver = await _seed_morning_medication(session, tenant)
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        clock.set("2026-08-19T01:00:00+00:00")
        await jobs.run_due_jobs(session, sysscope)          # ครั้งที่ 1
        await session.commit()

        clock.advance(minutes=11)
        await jobs.run_due_jobs(session, sysscope)          # ครั้งที่ 2
        await session.commit()

        clock.advance(minutes=21)
        await jobs.run_due_jobs(session, sysscope)          # ครั้งที่ 3 — ถามตรง ๆ
        await session.commit()

        job = (await jobs.open_jobs(session, sysscope, patient.patient_id))[0]
        assert job.attempts == 3, "ต้องเตือนครบ max_attempts ก่อน"

        clock.advance(minutes=21)
        summary = await jobs.run_due_jobs(session, sysscope)  # ครบแล้ว → missed → escalate
        await session.commit()

        assert summary["missed"] == 1
        assert summary["escalated"] == 1

        job = (await jobs.open_jobs(session, sysscope, patient.patient_id))[0]
        assert job.state == "escalated"

        rows = await notifications(session, tenant, patient.patient_id, "caregiver")
        assert len(rows) == 1
        assert rows[0].target_principal_id == caregiver.principal_id

        # เตือนผู้ป่วย 3 ครั้ง — ไม่เกิน max_attempts (กัน notification storm)
        patient_msgs = await notifications(session, tenant, patient.patient_id, "patient")
        assert len(patient_msgs) == 3
        assert "ทำแล้วหรือยัง" in patient_msgs[-1].text, "ครั้งสุดท้ายต้องถามตรง ๆ"

        events = await audit_events(session, tenant)
        care_types = {e.care_event_type for e in events}
        assert "care.medication.missed" in care_types
        assert "care.escalated" in care_types


async def test_s2_more_reminders_never_sent_after_max_attempts(session, tenant):
    """เกิน max_attempts แล้วห้ามเตือนซ้ำอีก — escalation_rules"""
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, _ = await _seed_morning_medication(session, tenant)
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        for _ in range(6):
            await jobs.run_due_jobs(session, sysscope)
            await session.commit()
            clock.advance(minutes=30)

        patient_msgs = await notifications(session, tenant, patient.patient_id, "patient")
        assert len(patient_msgs) == 3


async def test_caregiver_acknowledge_stops_the_loop(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, _ = await _seed_morning_medication(session, tenant)
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        for _ in range(4):
            await jobs.run_due_jobs(session, sysscope)
            await session.commit()
            clock.advance(minutes=25)

        job = (await jobs.open_jobs(session, sysscope, patient.patient_id))[0]
        assert job.state == "escalated"

        caregiver_scope = scope_for(tenant, "user-2")
        job = await jobs.caregiver_acknowledge(session, caregiver_scope, job.care_job_id)
        await session.commit()

        assert job.state == "acknowledged"
        assert job.next_attempt_at is None

        before = len(await notifications(session, tenant, patient.patient_id))
        clock.advance(hours=2)
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()
        after = len(await notifications(session, tenant, patient.patient_id))
        assert before == after, "รับเรื่องแล้วต้องไม่มีข้อความใหม่อีก"


async def test_trail_order_survives_events_that_share_a_timestamp(session, tenant):
    """audit ที่เรียงไม่ได้ = ตอบไม่ได้ว่าอะไรเกิดก่อนอะไร ซึ่งทำลายเหตุผลทั้งหมดของการมี audit

    หลาย event ใน transaction เดียวมี occurred_at เท่ากันเป๊ะได้จริง และ Postgres
    ไม่รับประกันลำดับของแถวที่ ORDER BY เท่ากัน — `sequence` ของ `event/v1` เป็นตัวตัดสิน
    """
    from care_addons.ap_audit import services as audit_svc

    with FakeClock("2026-08-19T00:30:00+00:00"):
        patient, _ = await _seed_morning_medication(session, tenant)
        scope = scope_for(tenant, correlation_id="corr-same-instant")

        written = []
        for kind in ("JOB_CREATED", "EXECUTION_STARTED", "STATE_TRANSITION", "JOB_COMPLETED"):
            event = await audit_svc.emit(
                session,
                scope,
                event_type=kind,
                subject_type="record",
                subject_id=patient.patient_id,
            )
            written.append(event.event_id)
        await session.commit()
        session.expunge_all()      # บังคับให้อ่านกลับมาจาก DB จริง ไม่ใช่จาก identity map

        trail_events = await audit.trail(session, scope, "corr-same-instant")
        assert len({e.occurred_at for e in trail_events}) == 1   # เวลาเดียวกันหมดจริง
        assert [e.event_id for e in trail_events] == written
