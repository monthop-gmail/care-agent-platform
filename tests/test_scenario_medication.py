"""Scenario S4, S9 — medication memory และเส้นที่ AI ข้ามไม่ได้

    S4  หมอ A เพิ่มยา หมอ B ลดยาตัวเดียวกัน → conflict ไม่เลือกข้าง ต้อง reconcile
    S9  agent พยายามแก้ medication เอง       → ถูก policy ปฏิเสธ
"""

from __future__ import annotations

import pytest
from core.clock import FakeClock
from core.tenancy import Principal

from care_addons.ap_policy.engine import evaluate
from care_addons.care_medication import services as meds
from tests.conftest import audit_events, scope_for, setup_patient

DOCTOR_A = {"doctor_name": "หมอ A", "specialty": "neurology"}
DOCTOR_B = {"doctor_name": "หมอ B", "specialty": "cardiology"}
HUMAN = Principal(type="human", id="user-1", display_name="ลูกสาว")
AGENT = Principal(type="agent", id="care-agent")


async def _confirmed(session, scope, patient_id, *, name, dose, prescribed_by, medication_id=None):
    version = await meds.propose_version(
        session,
        scope,
        patient_id=patient_id,
        name=name,
        medication_id=medication_id,
        schedule=[{"time": "07:00", "relation_to_meal": "before_meal", "dose": dose}],
        instruction_source="doctor_instruction",
        prescribed_by=prescribed_by,
    )
    return await meds.confirm_version(session, scope, version.version_id, confirmed_by=HUMAN)


async def test_proposal_is_never_active_by_itself(session, tenant):
    """AI เสนอได้ แต่คำสั่งยังไม่มีผลจนกว่าคนจะยืนยัน (ADR-0006 ข้อ 3)"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        version = await meds.propose_version(
            session,
            scope,
            patient_id=patient.patient_id,
            name="Donepezil",
            schedule=[{"time": "20:00", "relation_to_meal": "bedtime", "dose": "1 tablet"}],
            instruction_source="doctor_instruction",
            prescribed_by=DOCTOR_A,
        )
        await session.commit()

        assert version.status == "proposed"
        assert await meds.current_regimen(session, scope, patient.patient_id) == []


async def test_s9_agent_cannot_confirm_medication(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        version = await meds.propose_version(
            session,
            scope,
            patient_id=patient.patient_id,
            name="Donepezil",
            schedule=[{"time": "20:00", "relation_to_meal": "bedtime", "dose": "1 tablet"}],
            instruction_source="doctor_instruction",
        )
        await session.commit()

        with pytest.raises(meds.MedicationRuleViolation) as excinfo:
            await meds.confirm_version(session, scope, version.version_id, confirmed_by=AGENT)
        assert "ต้องเป็นคน" in str(excinfo.value)

        # policy ก็ต้องบอกแบบเดียวกันโดยไม่ต้องพึ่งโค้ดของโดเมน
        assert not evaluate("medication.regimen.write").may_act_now
        assert not evaluate("medication.regimen.stop").may_act_now
        # แต่การเตือนกินยาและการเสนอยังทำได้ ไม่งั้นระบบไร้ประโยชน์
        assert evaluate("medication.reminder.send").may_act_now
        assert evaluate("medication.regimen.propose").may_act_now


async def test_version_chain_is_append_only(session, tenant):
    """ADR-0005: เวอร์ชันเก่าไม่ถูกลบ — ตอบได้ทั้ง 'ตอนนี้' และ 'เมื่อก่อน'"""
    with FakeClock("2026-08-01T01:00:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)

        v1 = await _confirmed(
            session, scope, patient.patient_id, name="Med X", dose="1 tablet", prescribed_by=DOCTOR_A
        )
        await session.commit()

        clock.set("2026-08-10T01:00:00+00:00")
        v2 = await _confirmed(
            session,
            scope,
            patient.patient_id,
            name="Med X",
            dose="0.5 tablet",
            prescribed_by=DOCTOR_B,
            medication_id=v1.medication_id,
        )
        await session.commit()

        chain = await meds.history(session, scope, v1.medication_id)
        assert [v.status for v in chain] == ["superseded", "active"]
        assert chain[0].superseded_by == v2.version_id
        assert chain[0].schedule[0]["dose"] == "1 tablet", "ของเก่าต้องยังอ่านได้เหมือนเดิม"

        current = await meds.current_regimen(session, scope, patient.patient_id)
        assert len(current) == 1
        assert current[0].schedule[0]["dose"] == "0.5 tablet"

        clock.set("2026-08-18T01:00:00+00:00")
        stopped = await meds.stop_medication(
            session,
            scope,
            v1.medication_id,
            patient_id=patient.patient_id,
            stopped_by=HUMAN,
            reason="หมอ A ให้หยุด",
        )
        await session.commit()

        assert stopped.status == "stopped"
        assert await meds.current_regimen(session, scope, patient.patient_id) == []
        assert len(await meds.history(session, scope, v1.medication_id)) == 3


async def test_s4_conflict_between_two_doctors(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)

        # ยาชื่อเดียวกันแต่เป็นคนละใบสั่ง (คนละ medication_id) — เกิดขึ้นจริงเมื่อมีหมอหลายคน
        await _confirmed(
            session, scope, patient.patient_id, name="Med X", dose="1 tablet", prescribed_by=DOCTOR_A
        )
        await _confirmed(
            session, scope, patient.patient_id, name="med x", dose="0.5 tablet", prescribed_by=DOCTOR_B
        )
        await session.commit()

        current = await meds.current_regimen(session, scope, patient.patient_id)
        assert len(current) == 2
        assert {v.status for v in current} == {"needs_reconciliation"}, "ต้องหยุดรอคน ไม่ใช่เลือกข้าง"

        events = await audit_events(session, tenant, patient.patient_id)
        conflict = [e for e in events if e.care_event_type == "care.medication.conflict"]
        assert conflict, "ต้องมี event care.medication.conflict"
        assert conflict[0].attributes["requires"] == "reconciliation_by_human"
        assert len(conflict[0].attributes["versions"]) == 2

        # UI ที่แสดงยามื้อเช้าต้องรู้ว่ารายการนี้ยังสะสางไม่เสร็จ
        doses = await meds.doses_for_meal(session, scope, patient.patient_id, "before_meal")
        assert all(d["needs_reconciliation"] for d in doses)


async def test_relation_to_meal_must_be_structured(session, tenant):
    """ADR-0005 ข้อ 2 — ค่าที่ไม่รู้จักถูกปฏิเสธที่ intake ห้ามเดา"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        with pytest.raises(ValueError, match="relation_to_meal"):
            await meds.propose_version(
                session,
                scope,
                patient_id=patient.patient_id,
                name="Med Y",
                schedule=[{"time": "07:00", "relation_to_meal": "หลังอาหารเช้านิดหน่อย", "dose": "1"}],
                instruction_source="patient_entry",
            )


async def test_reconciliation_summary_for_doctor_visit(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        v1 = await _confirmed(
            session, scope, patient.patient_id, name="Med X", dose="1 tablet", prescribed_by=DOCTOR_A
        )
        await meds.stop_medication(
            session,
            scope,
            v1.medication_id,
            patient_id=patient.patient_id,
            stopped_by=HUMAN,
            reason="หยุดตามคำสั่ง",
        )
        await session.commit()

        summary = await meds.reconciliation_summary(session, scope, patient.patient_id)
        assert summary["active_count"] == 0
        assert "Med X" in summary["stopped"]
        assert len(summary["changes"]) == 2, "สรุปต้องสร้างจาก chain จริง ไม่ใช่ข้อมูลที่เก็บซ้ำ"
