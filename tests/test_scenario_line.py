"""M4 — ผู้ป่วยใช้งานจริงผ่าน LINE

ทดสอบทั้งขาออก (reminder ถึงมือผู้ป่วย) และขาเข้า (ผู้ป่วยตอบกลับแล้วระบบเข้าใจ)
โดยสลับ transport เป็นตัวดักข้อความ — ไม่ยิง LINE API จริง
"""

from __future__ import annotations

import pytest

from care_addons.ap_tenancy.clock import FakeClock
from care_addons.ap_tenancy.services import Principal
from care_addons.care_escalation import services as jobs
from care_addons.care_journal import services as journal
from care_addons.care_line import inbound
from care_addons.care_line import services as line
from care_addons.care_medication import services as meds
from care_addons.care_routine import services as routines
from tests.conftest import audit_events, notifications, scope_for, setup_patient, system_scope

CHANNEL = "line-channel-test"
PATIENT_LINE_ID = "U-patient-0001"
CAREGIVER_LINE_ID = "U-caregiver-0001"

PROFILE = {"routine": True, "medication": True, "memory_assistance": True, "caregiver_escalation": True}


@pytest.fixture
def outbox(monkeypatch):
    """ดักข้อความที่จะถูกส่งออก LINE"""
    sent: list[dict] = []

    async def fake_transport(channel_id: str, line_user_id: str, text: str):
        sent.append({"channel_id": channel_id, "line_user_id": line_user_id, "text": text})
        return True, None

    monkeypatch.setattr(line, "transport", fake_transport)
    return sent


async def _bind(session, tenant, patient, *, line_user_id, principal_id, role, display_name=""):
    scope = scope_for(tenant)
    code = await line.create_pairing_code(
        session,
        scope,
        patient_id=patient.patient_id,
        principal_id=principal_id,
        role=role,
        display_name=display_name,
    )
    await session.commit()
    binding = await line.redeem_pairing_code(
        session, code=code.code, channel_id=CHANNEL, line_user_id=line_user_id
    )
    await session.commit()
    return binding


async def _patient_with_morning_medication(session, tenant):
    patient, caregiver = await setup_patient(session, tenant, profile=PROFILE)
    await routines.add_routine(
        session,
        scope_for(tenant),
        patient_id=patient.patient_id,
        kind="medication",
        label="ยาเช้า หลังอาหาร",
        scheduled_time="08:00",
    )
    await session.commit()
    return patient, caregiver


# ---------- การจับคู่บัญชี ----------

def test_intent_parser_never_guesses():
    """ฟังก์ชันบริสุทธิ์ — ข้อความที่ไม่เข้าเกณฑ์ต้องเป็น unknown ไม่ใช่เดาเป็นอย่างอื่น"""
    assert inbound.interpret("ทำแล้วครับ").kind == "confirm"
    assert inbound.interpret("ยังไม่ได้ทำเลย").kind == "not_yet"
    assert inbound.interpret("ยัง").kind == "not_yet"
    assert inbound.interpret("วันนี้วันอะไร").kind == "date"
    assert inbound.interpret("พรุ่งนี้ต้องทำอะไรบ้าง") == inbound.Intent("plan", "พรุ่งนี้")
    assert inbound.interpret("กินยาแล้วยัง").kind == "medication_status"
    assert inbound.interpret("จด ช่วงนี้เวียนหัว") == inbound.Intent("journal", "ช่วงนี้เวียนหัว")
    assert inbound.interpret("ผูก ABC123") == inbound.Intent("pair", "ABC123")
    for text in ["ไปไหนมา", "อากาศร้อนจัง", "ช่วยจองตั๋วเครื่องบินให้หน่อย", ""]:
        assert inbound.interpret(text).kind == "unknown", text


async def test_pairing_binds_line_account_to_patient(session, tenant, outbox):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant, profile=PROFILE)
        await session.commit()

        binding = await _bind(
            session,
            tenant,
            patient,
            line_user_id=PATIENT_LINE_ID,
            principal_id=patient.patient_id,
            role="patient",
            display_name="คุณยาย",
        )
        assert binding.patient_id == patient.patient_id
        assert binding.tenant_id == tenant

        found = await line.find_binding(
            session, channel_id=CHANNEL, line_user_id=PATIENT_LINE_ID
        )
        assert found is not None and found.role == "patient"


async def test_pairing_code_is_single_use_and_expires(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant, profile=PROFILE)
        await session.commit()
        scope = scope_for(tenant)

        code = await line.create_pairing_code(
            session, scope, patient_id=patient.patient_id,
            principal_id=patient.patient_id, role="patient",
        )
        await session.commit()
        await line.redeem_pairing_code(
            session, code=code.code, channel_id=CHANNEL, line_user_id=PATIENT_LINE_ID
        )
        await session.commit()

        with pytest.raises(line.PairingError, match="ถูกใช้ไปแล้ว"):
            await line.redeem_pairing_code(
                session, code=code.code, channel_id=CHANNEL, line_user_id="U-someone-else"
            )

        expiring = await line.create_pairing_code(
            session, scope, patient_id=patient.patient_id,
            principal_id=patient.patient_id, role="patient", ttl_minutes=30,
        )
        await session.commit()
        clock.advance(minutes=31)
        with pytest.raises(line.PairingError, match="หมดอายุ"):
            await line.redeem_pairing_code(
                session, code=expiring.code, channel_id=CHANNEL, line_user_id="U-late"
            )

        with pytest.raises(line.PairingError, match="ไม่ถูกต้อง"):
            await line.redeem_pairing_code(
                session, code="ZZZZZZ", channel_id=CHANNEL, line_user_id="U-guess"
            )


async def test_pairing_code_never_lands_in_the_audit_log(session, tenant):
    """ใครอ่าน audit ได้ ต้องผูกบัญชีแทนผู้ป่วยไม่ได้"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant, profile=PROFILE)
        await session.commit()
        code = await line.create_pairing_code(
            session, scope_for(tenant), patient_id=patient.patient_id,
            principal_id=patient.patient_id, role="patient",
        )
        await session.commit()

        events = await audit_events(session, tenant, patient.patient_id)
        dumped = str([e.attributes for e in events])
        assert code.code not in dumped


# ---------- ขาออก: reminder ถึงมือผู้ป่วยจริง ----------

async def test_reminder_is_actually_delivered_to_line(session, tenant, outbox):
    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient, _ = await _patient_with_morning_medication(session, tenant)
        await _bind(
            session, tenant, patient, line_user_id=PATIENT_LINE_ID,
            principal_id=patient.patient_id, role="patient",
        )
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        clock.set("2026-08-19T01:00:00+00:00")
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

        assert len(outbox) == 1
        assert outbox[0]["line_user_id"] == PATIENT_LINE_ID
        assert "ยาเช้า หลังอาหาร" in outbox[0]["text"]
        assert "ทำแล้ว" in outbox[0]["text"], "ต้องบอกวิธีตอบกลับให้ผู้ป่วยด้วย"

        rows = await notifications(session, tenant, patient.patient_id, "patient")
        assert rows[0].delivery_status == "sent"
        assert rows[0].delivery_error is None


async def test_delivery_failure_is_visible_not_silent(session, tenant, monkeypatch):
    """ส่งไม่ออกต้องเห็นได้ — ไม่ใช่บันทึกว่าส่งแล้วทั้งที่ผู้ป่วยไม่เคยได้รับ"""
    async def broken_transport(channel_id, line_user_id, text):
        return False, "LINE API ล่ม"

    monkeypatch.setattr(line, "transport", broken_transport)

    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient, _ = await _patient_with_morning_medication(session, tenant)
        await _bind(
            session, tenant, patient, line_user_id=PATIENT_LINE_ID,
            principal_id=patient.patient_id, role="patient",
        )
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        clock.set("2026-08-19T01:00:00+00:00")
        summary = await jobs.run_due_jobs(session, sysscope)   # ต้องไม่ระเบิด
        await session.commit()
        assert summary["reminded"] == 1

        rows = await notifications(session, tenant, patient.patient_id, "patient")
        assert rows[0].delivery_status == "failed"
        assert "LINE API ล่ม" in rows[0].delivery_error

        events = await audit_events(session, tenant, patient.patient_id)
        failures = [e for e in events if e.event_type == "EXECUTION_FAILED"]
        assert failures and "ส่งไม่ออก" in failures[-1].error


async def test_unbound_patient_does_not_block_the_loop(session, tenant, outbox):
    """ยังไม่ได้ผูก LINE = ส่งไม่ถึง แต่ closed loop ต้องเดินต่อและ escalate ตามปกติ"""
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, _ = await _patient_with_morning_medication(session, tenant)
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        for _ in range(4):
            await jobs.run_due_jobs(session, sysscope)
            await session.commit()
            clock.advance(minutes=25)

        rows = await notifications(session, tenant, patient.patient_id, "patient")
        assert rows and all(r.delivery_status == "failed" for r in rows)
        assert all("ยังไม่ได้ผูกบัญชี" in (r.delivery_error or "") for r in rows)

        job = (await jobs.open_jobs(session, sysscope, patient.patient_id))[0]
        assert job.state == "escalated", "ส่งไม่ถึงผู้ป่วยยิ่งต้อง escalate ให้ผู้ดูแล"


# ---------- ขาเข้า: ผู้ป่วยตอบกลับ ----------

async def _reminded_job(session, tenant, patient):
    sysscope = system_scope(tenant)
    await routines.materialize_day(session, sysscope, patient.patient_id)
    await session.commit()
    await jobs.run_due_jobs(session, sysscope)
    await session.commit()
    return (await jobs.open_jobs(session, sysscope, patient.patient_id))[0]


async def test_patient_confirms_over_line(session, tenant, outbox):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_morning_medication(session, tenant)
        binding = await _bind(
            session, tenant, patient, line_user_id=PATIENT_LINE_ID,
            principal_id=patient.patient_id, role="patient",
        )
        job = await _reminded_job(session, tenant, patient)

        reply = await inbound.handle_message(session, binding, "ทานแล้วครับ")
        await session.commit()

        assert "เรียบร้อย" in reply
        refreshed = await jobs.get_job(session, scope_for(tenant), job.care_job_id)
        assert refreshed.state == "confirmed"
        assert refreshed.evidence["kind"] == "patient_confirmed"
        assert refreshed.evidence["recorded_by"]["id"] == patient.patient_id


async def test_patient_says_not_yet_and_gets_reminded_again(session, tenant, outbox):
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, _ = await _patient_with_morning_medication(session, tenant)
        binding = await _bind(
            session, tenant, patient, line_user_id=PATIENT_LINE_ID,
            principal_id=patient.patient_id, role="patient",
        )
        job = await _reminded_job(session, tenant, patient)

        reply = await inbound.handle_message(session, binding, "ยัง")
        await session.commit()
        assert "เตือน" in reply

        refreshed = await jobs.get_job(session, scope_for(tenant), job.care_job_id)
        assert refreshed.state == "acknowledged"
        assert refreshed.state != "confirmed", "ตอบว่ายัง ต้องไม่ถูกบันทึกว่าทำแล้ว"

        clock.advance(minutes=25)
        await jobs.run_due_jobs(session, system_scope(tenant))
        await session.commit()
        assert len(outbox) >= 2, "ต้องได้รับการเตือนซ้ำจริง"


async def test_s7_over_line_no_evidence_means_no_data(session, tenant, outbox):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_morning_medication(session, tenant)
        binding = await _bind(
            session, tenant, patient, line_user_id=PATIENT_LINE_ID,
            principal_id=patient.patient_id, role="patient",
        )
        await _reminded_job(session, tenant, patient)

        reply = await inbound.handle_message(session, binding, "กินยาแล้วยัง")
        await session.commit()

        assert "ยังไม่มีข้อมูล" in reply
        for word in ["น่าจะ", "คิดว่า", "ปกติแล้ว", "คงจะ"]:
            assert word not in reply


async def test_orientation_over_line(session, tenant, outbox):
    with FakeClock("2026-08-19T00:15:00+00:00"):
        patient, _ = await _patient_with_morning_medication(session, tenant)
        binding = await _bind(
            session, tenant, patient, line_user_id=PATIENT_LINE_ID,
            principal_id=patient.patient_id, role="patient",
        )
        await session.commit()

        answers = [
            await inbound.handle_message(session, binding, "วันนี้วันอะไร") for _ in range(3)
        ]
        await session.commit()
        assert len(set(answers)) == 1
        assert "วันพุธที่ 19 สิงหาคม" in answers[0]


async def test_unknown_message_offers_help_instead_of_guessing(session, tenant, outbox):
    """🔒 ADR-0008 — ไม่ส่งต่อให้ LLM และไม่เดาคำตอบ"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_morning_medication(session, tenant)
        binding = await _bind(
            session, tenant, patient, line_user_id=PATIENT_LINE_ID,
            principal_id=patient.patient_id, role="patient",
        )
        await session.commit()

        reply = await inbound.handle_message(session, binding, "ช่วยเปลี่ยนยาให้หน่อย")
        await session.commit()

        assert reply == inbound.HELP_TEXT
        assert "ยังไม่เข้าใจ" in reply
        # ต้องไม่มีการแตะข้อมูลยาเลย
        assert await meds.current_regimen(session, scope_for(tenant), patient.patient_id) == []


async def test_patient_can_record_a_question_for_the_doctor(session, tenant, outbox):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_morning_medication(session, tenant)
        binding = await _bind(
            session, tenant, patient, line_user_id=PATIENT_LINE_ID,
            principal_id=patient.patient_id, role="patient",
        )
        await session.commit()

        reply = await inbound.handle_message(session, binding, "จด ยาตัวนี้ทำให้ง่วงหรือไม่")
        await session.commit()
        assert "จดไว้ให้แล้ว" in reply

        questions = await journal.open_questions(session, scope_for(tenant), patient.patient_id)
        assert len(questions) == 1
        assert questions[0].text == "ยาตัวนี้ทำให้ง่วงหรือไม่"

        await inbound.handle_message(session, binding, "จด เมื่อเช้าเวียนหัวตอนลุกขึ้น")
        await session.commit()
        entries = await journal.recent_entries(session, scope_for(tenant), patient.patient_id)
        # 🔒 ต้องเก็บคำพูดต้นฉบับไว้ ไม่เขียนใหม่ให้
        assert any(e.text == "เมื่อเช้าเวียนหัวตอนลุกขึ้น" for e in entries)


async def test_caregiver_can_take_over_from_line(session, tenant, outbox):
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, caregiver = await _patient_with_morning_medication(session, tenant)
        binding = await _bind(
            session, tenant, patient, line_user_id=CAREGIVER_LINE_ID,
            principal_id=caregiver.principal_id, role="caregiver", display_name="ลูกสาว",
        )
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()
        for _ in range(4):
            await jobs.run_due_jobs(session, sysscope)
            await session.commit()
            clock.advance(minutes=25)

        job = (await jobs.open_jobs(session, sysscope, patient.patient_id))[0]
        assert job.state == "escalated"

        reply = await inbound.handle_message(session, binding, "รับเรื่อง")
        await session.commit()
        assert "รับทราบ" in reply

        refreshed = await jobs.get_job(session, scope_for(tenant), job.care_job_id)
        assert refreshed.state == "acknowledged"


async def test_medication_list_hides_doses_that_need_reconciliation(session, tenant, outbox):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_morning_medication(session, tenant)
        binding = await _bind(
            session, tenant, patient, line_user_id=PATIENT_LINE_ID,
            principal_id=patient.patient_id, role="patient",
        )
        scope = scope_for(tenant)
        for dose in ("1 เม็ด", "ครึ่งเม็ด"):
            version = await meds.propose_version(
                session, scope, patient_id=patient.patient_id, name="Med X",
                schedule=[{"time": "08:00", "relation_to_meal": "after_meal", "dose": dose}],
                instruction_source="doctor_instruction",
            )
            await meds.confirm_version(
                session, scope, version.version_id, confirmed_by=Principal(type="human", id="user-1")
            )
        await session.commit()

        reply = await inbound.handle_message(session, binding, "วันนี้กินยาอะไร")
        await session.commit()

        assert "รอผู้ดูแลตรวจสอบ" in reply
        assert "เม็ด" not in reply.replace("ครึ่งเม็ด", "").replace("1 เม็ด", "")
