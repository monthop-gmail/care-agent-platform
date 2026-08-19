"""Scenario S3 — ตื่นมาไม่รู้วันไหน

blueprint บอกไว้ชัดว่านี่ **ไม่ใช่ edge case** แต่เป็น scenario หลักที่ต้องมี automated test
ตั้งแต่ MVP — ถามซ้ำกี่ครั้งก็ต้องได้คำตอบเดิม และต้องไม่มีถ้อยคำที่ทำให้ผู้ป่วยรู้สึกผิด
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from core.clock import FakeClock, now
from core.tenancy import Principal

from care_addons.care_appointment import services as appointments
from care_addons.care_medication import services as meds
from care_addons.care_orientation import services as orientation
from care_addons.care_routine import services as routines
from tests.conftest import audit_events, scope_for, setup_patient, system_scope

PROFILE = {
    "routine": True,
    "medication": True,
    "appointment": True,
    "memory_assistance": True,
    "caregiver_escalation": True,
}

# 07:15 ตามเวลาไทย ของวันพุธที่ 19 สิงหาคม 2026 (ตัวอย่างใน blueprint เขียน "อังคาร" ไว้ลอย ๆ
# แต่ปฏิทินจริงเป็นวันพุธ — เทสยึดปฏิทิน ไม่ยึดตัวอย่าง)
MORNING = "2026-08-19T00:15:00+00:00"


async def _patient_with_day(session, tenant):
    patient, _ = await setup_patient(session, tenant, profile=PROFILE)
    scope = scope_for(tenant)
    patient.home_label = "บ้าน"
    for kind, label, at in [
        ("meal", "อาหารเช้า", "07:30"),
        ("medication", "ยาเช้า หลังอาหาร", "08:00"),
        ("activity", "เดินออกกำลังกาย 20 นาที", "10:00"),
    ]:
        await routines.add_routine(
            session, scope, patient_id=patient.patient_id, kind=kind, label=label, scheduled_time=at
        )
    await session.commit()
    await routines.materialize_day(session, system_scope(tenant), patient.patient_id)
    await session.commit()
    return patient


async def test_s3_same_answer_no_matter_how_many_times_asked(session, tenant):
    with FakeClock(MORNING):
        patient = await _patient_with_day(session, tenant)
        scope = scope_for(tenant, patient.patient_id)

        answers = []
        for _ in range(3):
            answers.append((await orientation.answer_date(session, scope, patient.patient_id))["answer"])
        await session.commit()

        assert len(set(answers)) == 1, "ถามซ้ำต้องได้คำตอบเดิมเป๊ะ"
        assert "วันพุธที่ 19 สิงหาคม" in answers[0]
        assert "07:15" in answers[0]

        # ห้ามมีถ้อยคำที่ทำให้ผู้ป่วยรู้สึกผิดที่ถามซ้ำ
        for word in ["อีกแล้ว", "เพิ่งบอก", "บอกไปแล้ว", "ลืม", "ครั้งที่"]:
            assert word not in answers[-1]

        # แต่ต้องบันทึกไว้ว่าถูกถาม 3 ครั้ง — ข้อมูลนี้มีค่าสำหรับผู้ดูแล
        events = await audit_events(session, tenant, patient.patient_id)
        delivered = [e for e in events if e.care_event_type == "care.orientation.delivered"]
        assert len(delivered) == 3


async def test_five_layers_say_when_they_have_no_data(session, tenant):
    """🔒 ไม่มีข้อมูล = บอกว่าไม่มี ห้ามเดา (ADR-0006 ข้อ 5)"""
    with FakeClock(MORNING):
        patient, _ = await setup_patient(session, tenant, profile=PROFILE)
        await session.commit()
        scope = scope_for(tenant)

        layers = await orientation.five_layers(session, scope, patient.patient_id)

        assert "07:15" in layers["time"]["answer"]
        assert layers["date"]["answer"] == "วันพุธที่ 19 สิงหาคม"
        assert layers["place"]["known"] is False
        assert layers["place"]["answer"] == orientation.NO_DATA
        assert layers["person"]["known"] is False
        assert layers["plan"]["known"] is False


async def test_daily_brief_reads_like_something_a_person_can_follow(session, tenant):
    with FakeClock(MORNING):
        patient = await _patient_with_day(session, tenant)
        scope = scope_for(tenant)

        proposed = await meds.propose_version(
            session,
            scope,
            patient_id=patient.patient_id,
            name="Donepezil",
            schedule=[{"time": "08:00", "relation_to_meal": "after_meal", "dose": "1 เม็ด"}],
            instruction_source="doctor_instruction",
        )
        await meds.confirm_version(
            session, scope, proposed.version_id, confirmed_by=Principal(type="human", id="user-1")
        )
        await session.commit()

        brief = await orientation.daily_brief(session, scope, patient.patient_id)
        await session.commit()

        assert brief["date"] == "วันพุธที่ 19 สิงหาคม"
        assert brief["place"] == "บ้าน"
        assert brief["appointments"] == []
        assert len(brief["medications"]) == 1
        assert len(brief["plan"]) == 3

        text = brief["text"]
        assert "วันพุธที่ 19 สิงหาคม" in text
        assert "วันนี้ไม่มีนัดคุณหมอครับ" in text
        assert "อาหารเช้า" in text          # รายการถัดไปที่ยังไม่ได้ทำ
        # 🔒 ห้ามมีถ้อยคำเชิงวินิจฉัยหรือตำหนิใน daily brief
        for word in ["อาการ", "แย่ลง", "ผิดปกติ", "ลืม"]:
            assert word not in text


async def test_daily_brief_with_appointment_and_unreconciled_medication(session, tenant):
    with FakeClock(MORNING):
        patient = await _patient_with_day(session, tenant)
        scope = scope_for(tenant)

        await appointments.create_appointment(
            session,
            scope,
            patient_id=patient.patient_id,
            starts_at=now() + timedelta(hours=7),
            doctor_name="สมชาย",
            purpose="ตรวจเลือด",
        )
        for dose in ("1 เม็ด", "ครึ่งเม็ด"):
            version = await meds.propose_version(
                session,
                scope,
                patient_id=patient.patient_id,
                name="Med X",
                schedule=[{"time": "08:00", "relation_to_meal": "after_meal", "dose": dose}],
                instruction_source="doctor_instruction",
            )
            await meds.confirm_version(
                session, scope, version.version_id, confirmed_by=Principal(type="human", id="user-1")
            )
        await session.commit()

        brief = await orientation.daily_brief(session, scope, patient.patient_id)
        await session.commit()

        assert len(brief["appointments"]) == 1
        assert "วันนี้มีนัดคุณหมอสมชาย" in brief["text"]
        # ยาที่ยังสะสางไม่เสร็จ ห้ามบอกจำนวนเม็ดเหมือนปกติ (ADR-0005 ข้อ 4)
        assert all(m["needs_reconciliation"] for m in brief["medications"])
        assert "รอให้ผู้ดูแลตรวจสอบ" in brief["text"]


async def test_tomorrows_appointment_is_not_announced_as_a_task_for_today(session, tenant):
    """reminder ล่วงหน้าของนัดพรุ่งนี้ต้องไม่กลายเป็น "รายการถัดไป" ที่ผู้ป่วยต้องทำวันนี้"""
    with FakeClock(MORNING):
        patient = await _patient_with_day(session, tenant)
        scope = scope_for(tenant)

        appointment = await appointments.create_appointment(
            session,
            scope,
            patient_id=patient.patient_id,
            starts_at=now() + timedelta(hours=30),   # พรุ่งนี้
            doctor_name="สมชาย",
            purpose="ตรวจเลือด",
        )
        await appointments.schedule_reminders(session, scope, appointment.appointment_id)
        await session.commit()

        brief = await orientation.daily_brief(session, scope, patient.patient_id)
        await session.commit()

        assert brief["appointments"] == [], "นัดพรุ่งนี้ไม่ใช่นัดของวันนี้"
        assert "วันนี้ไม่มีนัดคุณหมอครับ" in brief["text"]
        assert "รายการถัดไปคือ อาหารเช้า" in brief["text"]
        assert "ในอีก" not in brief["text"], "ข้อความเตือนล่วงหน้าต้องไม่ปนมาเป็นงานของวันนี้"


async def test_temporal_memory_resolves_relative_days_from_the_calendar(session, tenant):
    """"พรุ่งนี้ต้องทำอะไรนะ?" — resolve จากปฏิทินจริง ไม่ใช่ให้ LLM เดา"""
    with FakeClock(MORNING):
        patient = await _patient_with_day(session, tenant)
        scope = scope_for(tenant)

        today = await orientation.what_happens_on(session, scope, patient.patient_id, "วันนี้")
        assert today["date"] == "2026-08-19"
        assert today["has_data"] is True
        assert len(today["plan"]) == 3

        tomorrow = await orientation.what_happens_on(session, scope, patient.patient_id, "พรุ่งนี้")
        await session.commit()
        assert tomorrow["date"] == "2026-08-20"
        assert tomorrow["date_answer"] == "วันพฤหัสบดีที่ 20 สิงหาคม"
        # ยังไม่ได้ materialize ของพรุ่งนี้ → ต้องบอกว่าไม่มีข้อมูล ไม่ใช่ "ไม่มีอะไรต้องทำ"
        assert tomorrow["has_data"] is False
        assert tomorrow["answer"] == orientation.NO_DATA

        with pytest.raises(orientation.UnknownTimeExpression):
            await orientation.what_happens_on(session, scope, patient.patient_id, "วันหลัง")
