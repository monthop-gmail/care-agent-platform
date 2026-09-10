"""`attributes` เป็นชุดปิด — audit เก็บตัวชี้ ไม่ใช่เนื้อหา (ADR-0011)

`event/v1` เปิด `metadata` ไว้ทั้งหมด ข้อจำกัดนี้เป็นของเราเอง เพราะเราเคยใช้ช่องเปิดนั้น
เก็บชื่อยาคู่ `patient_id` ข้อความที่ส่งให้ผู้ป่วยทั้งประโยค และเหตุผลที่คนพิมพ์
ลง audit ซึ่งเป็นที่ที่ **ลบไม่ได้**
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from core.clock import FakeClock

from care_addons.ap_audit import services as audit
from care_addons.ap_audit.attributes import DECLARED
from care_addons.care_escalation import services as jobs
from care_addons.care_medication import services as meds
from care_addons.care_routine import services as routines
from tests.conftest import (
    audit_events,
    notifications,
    scope_for,
    setup_patient,
    system_scope,
)

CARE_ADDONS = pathlib.Path(__file__).resolve().parents[1] / "care_addons"


async def test_a_key_that_nobody_declared_is_rejected(session, tenant):
    """คีย์ใหม่เข้า audit ไม่ได้จนกว่าจะมีคนมาเขียนบรรทัดในทะเบียน

    จุดที่สำคัญคือ *ตอนไหน* ที่มันพัง — พังตอนเขียนโค้ด ไม่ใช่ตอนมีคนมาอ่าน trail
    แล้วเจอชื่อคนไข้อยู่ในนั้นหนึ่งปีให้หลัง
    """
    patient, _ = await setup_patient(session, tenant)
    with pytest.raises(audit.EventRejected) as err:
        await audit.emit(
            session,
            scope_for(tenant),
            event_type="STATE_TRANSITION",
            subject_type="record",
            subject_id=patient.patient_id,
            attributes={"diagnosis_note": "คุณยายเริ่มสับสนเรื่องเวลามากขึ้น"},
        )
    assert "diagnosis_note" in str(err.value)
    await session.rollback()


async def test_a_declared_key_still_cannot_carry_a_sentence(session, tenant):
    """ประกาศแล้วไม่ได้แปลว่าใส่อะไรก็ได้ — ชนิดเป็นตัวบังคับว่ามันต้องเป็นรหัส

    เคสจริงที่กลัว: คนเห็นคีย์ที่ประกาศไว้แล้วก็ยัดข้อความของคนเข้าไปในคีย์นั้น
    """
    patient, _ = await setup_patient(session, tenant)
    with pytest.raises(audit.EventRejected) as err:
        await audit.emit(
            session,
            scope_for(tenant),
            event_type="STATE_TRANSITION",
            subject_type="record",
            subject_id=patient.patient_id,
            attributes={"capability": "หยุดยาเพราะคุณยายบอกว่าปวดเข่า"},
        )
    assert "capability" in str(err.value)
    await session.rollback()


async def test_error_details_is_closed_the_same_way(session, tenant):
    """`error/v1` นิยาม `details` ว่า `{"type": "object"}` — เปิดทั้งหมดเหมือน `metadata`

    ฟิลด์นี้ไม่มีใครพูดถึงตอนตกลงเรื่อง attributes · มันเป็นช่องที่สามที่รับอะไรก็ได้
    """
    await setup_patient(session, tenant)
    with pytest.raises(audit.EventRejected) as err:
        await audit.emit(
            session,
            scope_for(tenant),
            event_type="EXECUTION_FAILED",
            subject_type="execution",
            subject_id="exec-1",
            error=audit.make_error(
                "care.test.failed",
                "internal",
                "ทดสอบ",
                retryable=False,
                details={"raw_response": "ผู้ป่วยชื่อ ... ปฏิเสธจากปลายทาง"},
            ),
        )
    assert "raw_response" in str(err.value)
    await session.rollback()


def test_every_key_the_domain_writes_is_declared():
    """สแกนโค้ดจริง ไม่ใช่แค่เส้นทางที่เทสเดินผ่าน

    `emit()` reject ตอน runtime อยู่แล้ว แต่ path ที่เทสไม่ได้เดินจะไม่มีใครรู้จนกว่าจะ
    ไปเจอตอน production · ตัวนี้อ่าน AST ของทุกไฟล์ใน care_addons จึงเห็นคีย์ทั้งหมด
    ที่มีคนเขียนไว้ ไม่ว่าจะถูกเรียกหรือไม่
    """
    undeclared: dict[str, str] = {}
    for path in sorted(CARE_ADDONS.rglob("*.py")):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                # `details` ของ error/v1 เป็น open bag รูปเดียวกับ metadata เป๊ะ
                # ต่างกันแค่ไม่มีใครพูดถึงมัน — ใช้ทะเบียนเดียวกัน
                if kw.arg not in ("attributes", "details") or not isinstance(kw.value, ast.Dict):
                    continue
                for key in kw.value.keys:
                    if key is None:
                        continue      # `**spread` — ตรวจไม่ได้ที่นี่ ตกไปที่ emit() ตอน runtime
                    if isinstance(key, ast.Constant) and key.value not in DECLARED:
                        undeclared[key.value] = f"{path.name}:{key.lineno}"
    assert not undeclared, f"คีย์ที่ยังไม่ได้ประกาศใน ap_audit/attributes.py: {undeclared}"


async def test_reminder_audit_points_at_the_message_instead_of_copying_it(session, tenant):
    """เดิม audit เก็บข้อความเตือนทั้งประโยค ซึ่ง interpolate `job.label` (เช่นชื่อยา) เข้าไป

    ผลคือ trail ที่ลบไม่ได้ ถือข้อมูลสุขภาพของคนที่ระบุตัวได้ ทั้งที่ตัวข้อความมีที่อยู่
    ของมันเองอยู่แล้วที่ `care_notification` ซึ่งอ่านผ่านสิทธิ์ตามปกติ
    """
    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant)
        await routines.add_routine(
            session,
            scope_for(tenant),
            patient_id=patient.patient_id,
            kind="medication",
            label="ยาความดัน Amlodipine",
            scheduled_time="08:00",
            severity="medium",
        )
        await session.commit()
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        clock.set("2026-08-19T01:00:00+00:00")
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

        events = await audit_events(session, tenant, patient.patient_id)
        sent = [e for e in events if e.care_event_type == "care.reminder.sent"]
        assert sent, "ต้องมี event ตอนส่งเตือน"
        assert "Amlodipine" not in str(sent[0].attributes)
        assert "text" not in sent[0].attributes

        # ตัวข้อความยังอยู่ครบ — แค่ไม่ได้อยู่ใน audit
        outbox = await notifications(session, tenant, patient.patient_id)
        assert "Amlodipine" in outbox[0].text
        assert sent[0].attributes["notification_id"] == outbox[0].id


async def test_medication_audit_does_not_hold_the_drug_name(session, tenant):
    """ชื่อยา + patient_id = ข้อมูลสุขภาพของคนที่ระบุตัวได้ ไม่ใช่ metadata

    `subject_id` ของ event ชี้ไปที่ใบยาอยู่แล้ว คนที่มีสิทธิ์อ่านใบยาจึงอ่านชื่อได้
    ส่วนคนที่อ่านได้แค่ trail จะไม่ได้ชื่อยาไปฟรี ๆ
    """
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        version = await meds.propose_version(
            session,
            scope_for(tenant),
            patient_id=patient.patient_id,
            name="Donepezil 10mg",
            schedule=[{"time": "20:00", "relation_to_meal": "after_meal", "dose": "1 เม็ด"}],
            instruction_source="doctor_instruction",
            prescribed_by={"doctor_name": "หมอ A", "specialty": "neurology"},
        )
        await session.commit()

        events = await audit_events(session, tenant, patient.patient_id)
        proposed = [e for e in events if e.care_event_type == "care.medication.changed"]
        assert proposed
        assert "Donepezil" not in str(proposed[0].attributes)
        assert proposed[0].subject_id == version.version_id
