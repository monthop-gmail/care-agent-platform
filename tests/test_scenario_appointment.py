"""Scenario S5 — นัดตรวจเลือดพรุ่งนี้

    เตรียมตัวครบขั้น → พร้อมออกจากบ้าน
    ขั้นที่ค้างเกินเวลา → escalate ไป caregiver (ไม่ใช่เตือนผู้ป่วยซ้ำไปเรื่อย ๆ)
    ข้อกำหนดทางการแพทย์ (งดอาหาร) → ต้องมีเอกสาร ระบบเดาเองไม่ได้
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from core.clock import FakeClock
from core.tenancy import Principal

from care_addons.care_appointment import services as appointments
from care_addons.care_escalation import services as jobs
from care_addons.care_journal import services as journal
from care_addons.care_medication import services as meds
from tests.conftest import audit_events, notifications, scope_for, setup_patient, system_scope

PROFILE = {
    "routine": True,
    "medication": True,
    "appointment": True,
    "memory_assistance": True,
    "caregiver_escalation": True,
}


async def _appointment_tomorrow(session, tenant, *, hours_ahead: int = 24):
    patient, caregiver = await setup_patient(session, tenant, profile=PROFILE)
    scope = scope_for(tenant)
    from core.clock import now

    appointment = await appointments.create_appointment(
        session,
        scope,
        patient_id=patient.patient_id,
        starts_at=now() + timedelta(hours=hours_ahead),
        doctor_name="สมชาย",
        specialty="neurology",
        facility="โรงพยาบาลตัวอย่าง",
        purpose="ตรวจเลือด",
    )
    await session.commit()
    return patient, caregiver, appointment


async def test_appointment_creates_advance_reminders(session, tenant):
    with FakeClock("2026-08-18T01:00:00+00:00"):
        _, _, appointment = await _appointment_tomorrow(session, tenant, hours_ahead=48)
        scope = scope_for(tenant)

        created = await appointments.schedule_reminders(session, scope, appointment.appointment_id)
        await session.commit()
        assert len(created) == 2, "ต้องเตือนล่วงหน้า 24 และ 2 ชั่วโมงตาม contract"

        # เรียกซ้ำต้องไม่สร้างซ้ำ
        assert await appointments.schedule_reminders(session, scope, appointment.appointment_id) == []


async def test_fasting_requirement_needs_a_document(session, tenant):
    """🔒 ห้ามระบบเดาเองว่าต้องงดอาหารกี่ชั่วโมง (appointment_rules)"""
    with FakeClock("2026-08-18T01:00:00+00:00") as clock:
        _, _, appointment = await _appointment_tomorrow(session, tenant)
        scope = scope_for(tenant)
        due = clock.set("2026-08-18T01:00:00+00:00") + timedelta(hours=12)

        with pytest.raises(appointments.PreparationRuleViolation) as excinfo:
            await appointments.add_preparation_step(
                session,
                scope,
                appointment_id=appointment.appointment_id,
                kind="fasting_requirement",
                label="งดอาหารก่อนตรวจ",
                due_at=due,
            )
        assert "source_document" in str(excinfo.value)

        step = await appointments.add_preparation_step(
            session,
            scope,
            appointment_id=appointment.appointment_id,
            kind="fasting_requirement",
            label="ปฏิบัติตามข้อกำหนดเรื่องอาหารในเอกสารของโรงพยาบาล",
            due_at=due,
            source_document="ใบนัดตรวจเลือด รพ.ตัวอย่าง เลขที่ 12345",
        )
        await session.commit()
        assert step.source_document

        # แผนมาตรฐานต้องไม่มีข้อกำหนดทางการแพทย์ปนมาเอง
        assert all(kind != "fasting_requirement" for kind, *_ in appointments.DEFAULT_PLAN)


async def test_s5_preparation_completed_step_by_step(session, tenant):
    with FakeClock("2026-08-18T01:00:00+00:00"):
        patient, _, appointment = await _appointment_tomorrow(session, tenant)
        scope = scope_for(tenant)

        steps = await appointments.build_default_plan(session, scope, appointment.appointment_id)
        created = await appointments.start_preparation(session, scope, appointment.appointment_id)
        await session.commit()

        assert len(steps) == len(appointments.DEFAULT_PLAN)
        assert len(created) == len(steps), "ทุกขั้นต้องกลายเป็น care job ที่ติดตามได้"

        status = await appointments.readiness(session, scope, appointment.appointment_id)
        assert status["done"] == 0
        assert status["ready_to_leave"] is False

        for step in steps:
            await appointments.complete_step(session, scope, step.step_id)
        await session.commit()

        status = await appointments.readiness(session, scope, appointment.appointment_id)
        assert status["done"] == len(steps)
        assert status["ready_to_leave"] is True
        assert status["outstanding"] == []

        events = await audit_events(session, tenant, patient.patient_id)
        assert sum(1 for e in events if e.care_event_type == "care.appointment.prep_step_done") == len(steps)


async def test_s5_stalled_preparation_escalates_to_caregiver(session, tenant):
    """ผู้ป่วยไม่ตอบสนองตามเวลา → ผู้ดูแลต้องรู้ ไม่ใช่เตือนผู้ป่วยไปเรื่อย ๆ"""
    with FakeClock("2026-08-18T01:00:00+00:00") as clock:
        patient, caregiver, appointment = await _appointment_tomorrow(session, tenant)
        scope = scope_for(tenant)
        sysscope = system_scope(tenant)

        await appointments.build_default_plan(session, scope, appointment.appointment_id)
        await appointments.start_preparation(session, scope, appointment.appointment_id)
        await session.commit()

        # เดินเวลาไปจนเลยกำหนดของขั้นแรก แล้วปล่อยให้ engine ทำงานจนครบ max_attempts
        clock.set(appointment.starts_at - timedelta(hours=14, minutes=30))
        for _ in range(5):
            await jobs.run_due_jobs(session, sysscope)
            await session.commit()
            clock.advance(minutes=25)

        caregiver_msgs = await notifications(session, tenant, patient.patient_id, "caregiver")
        assert caregiver_msgs, "ขั้นเตรียมตัวที่ค้างต้องถูกส่งต่อให้ผู้ดูแล"
        assert caregiver_msgs[0].target_principal_id == caregiver.principal_id

        status = await appointments.readiness(session, scope, appointment.appointment_id)
        assert status["ready_to_leave"] is False
        assert status["outstanding"], "ขั้นที่ยังไม่ทำต้องยังค้างอยู่ ไม่ใช่ถูกปิดให้เอง"


async def test_acknowledging_a_reminder_is_not_attending_the_appointment(session, tenant):
    """🔒 "รับทราบว่ามีนัด" ≠ "ไปพบหมอมาแล้ว" — สองอย่างนี้ต้องแยกกันเด็ดขาด"""
    with FakeClock("2026-08-18T01:00:00+00:00") as clock:
        patient, _, appointment = await _appointment_tomorrow(session, tenant, hours_ahead=25)
        scope = scope_for(tenant)
        sysscope = system_scope(tenant)
        await appointments.schedule_reminders(session, scope, appointment.appointment_id)
        await session.commit()

        clock.set(appointment.starts_at - timedelta(hours=23, minutes=59))
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

        job = (await jobs.open_jobs(session, sysscope, patient.patient_id))[0]
        await jobs.acknowledge(session, scope_for(tenant, patient.patient_id), job.care_job_id)
        await session.commit()

        events = await audit_events(session, tenant, patient.patient_id)
        assert "care.reminder.acknowledged" in [e.care_event_type for e in events]
        assert "care.appointment.completed" not in [e.care_event_type for e in events]

        refreshed = await appointments.get_appointment(session, scope, appointment.appointment_id)
        assert refreshed.status == "scheduled"

        await appointments.complete_appointment(session, scope, appointment.appointment_id)
        await session.commit()
        events = await audit_events(session, tenant, patient.patient_id)
        assert "care.appointment.completed" in [e.care_event_type for e in events]


async def test_visit_brief_uses_only_recorded_data(session, tenant):
    with FakeClock("2026-08-18T01:00:00+00:00"):
        patient, _, appointment = await _appointment_tomorrow(session, tenant)
        scope = scope_for(tenant)

        await journal.record(
            session, scope, patient_id=patient.patient_id, text="ช่วงนี้เดินแล้วรู้สึกเวียนหัว"
        )
        await journal.record(
            session,
            scope,
            patient_id=patient.patient_id,
            text="ยาตัวนี้ทำให้ง่วงหรือไม่?",
            entry_type="question",
            target_specialty="neurology",
        )
        proposed = await meds.propose_version(
            session,
            scope,
            patient_id=patient.patient_id,
            name="Donepezil",
            schedule=[{"time": "20:00", "relation_to_meal": "bedtime", "dose": "1 เม็ด"}],
            instruction_source="doctor_instruction",
        )
        await meds.confirm_version(
            session, scope, proposed.version_id, confirmed_by=Principal(type="human", id="user-1")
        )
        await session.commit()

        brief = await appointments.visit_brief(session, scope, appointment.appointment_id)

        assert brief["appointment"]["specialty"] == "neurology"
        assert any("เวียนหัว" in o["text"] for o in brief["observations"])
        assert any("ง่วง" in q["text"] for q in brief["questions"])
        assert brief["medications"]["available"] is True
        assert brief["medications"]["active_count"] == 1
        assert "ไม่มีการตีความทางการแพทย์" in brief["note"]
