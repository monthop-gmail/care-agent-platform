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
from core.tenancy import Principal

from care_addons.ap_audit import services as audit
from care_addons.ap_audit.attributes import DECLARED, REASON_INTERPOLATIONS
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


async def test_audit_actor_is_a_pointer_not_a_name(session, tenant):
    """ชื่อคนไม่ได้อยู่ใน audit — `actor` เหลือแค่ type กับ id

    เจอเพราะเอากฎสามบรรทัดของร่าง RFC มาลองกับ payload จริง แล้วพบว่า
    `actor.display_name` ติดมาทุกใบ 112 จาก 112 · `display_name` เป็น optional
    ใน `identity/v1` (required มีแค่ type/id) การไม่ใส่จึงยัง conform
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
        await meds.confirm_version(
            session,
            scope_for(tenant),
            version.version_id,
            confirmed_by=Principal(type="human", id="user-1", display_name="ลูกสาว"),
        )
        await session.commit()

        events = await audit_events(session, tenant, patient.patient_id)
        assert events
        for e in events:
            assert set(e.actor) == {"type", "id"}, e.actor
            assert "ลูกสาว" not in str(e.actor)
            if e.evidence and "recorded_by" in e.evidence:
                assert set(e.evidence["recorded_by"]) == {"type", "id"}


# ── transition.reason ต้องเป็นข้อความที่โค้ดเราสร้างเอง (ADR-0012) ─────────────
#
# `_transition()` ของ care_escalation เป็นตัวรวมทางเดียวที่ส่ง reason ต่อเป็นพารามิเตอร์
# จึงยกเว้นที่ตัวมันเอง แล้วไปตรวจที่ผู้เรียกแทน
_REASON_PASSTHROUGH = {"_transition"}


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _reason_expressions():
    """ทุกที่ที่โค้ดกำหนดค่า transition.reason — (ไฟล์, บรรทัด, node, ฟังก์ชันที่อยู่)"""
    found = []
    for path in sorted(CARE_ADDONS.rglob("*.py")):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                targets = []
                for kw in node.keywords:
                    if kw.arg == "transition" and isinstance(kw.value, ast.Dict):
                        for key, value in zip(kw.value.keys, kw.value.values, strict=False):
                            if isinstance(key, ast.Constant) and key.value == "reason":
                                targets.append(value)
                if getattr(node.func, "id", "") == "_transition" and len(node.args) >= 5:
                    targets.append(node.args[4])
                for target in targets:
                    found.append((f"{path.parent.name}/{path.name}", target.lineno, target, fn.name))
    return found


def test_transition_reason_never_carries_a_value_from_outside_our_code():
    """audit ห้ามถือประโยคที่คนพิมพ์ — แม้ในฟิลด์ที่ `event/v1` นิยามเอง

    `attributes` ปิดด้วยทะเบียนแล้ว แต่ `transition.reason` เป็น `type: string` เปล่า ๆ
    ในสัญญา ไม่มีอะไรกันไว้เลย · เราเคยปล่อยให้ค่าที่ route รับมาไหลลงไปแปดทาง
    รวมถึงคำถามที่ **ผู้ป่วยพิมพ์เอง** และโน้ตของผู้ดูแลเรื่องการล้ม

    🔒 ตัวตรวจบอกได้แค่ว่าชื่อไหนถูกแทรก บอกไม่ได้ว่าค่าข้างในมาจากใคร —
       ทะเบียนใน ap_audit/attributes.py จึงเป็นคำตอบของคน ไม่ใช่ของเครื่อง
    """
    leaked = []
    for filename, lineno, node, fname in _reason_expressions():
        if fname in _REASON_PASSTHROUGH:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Name | ast.Attribute):
                continue
            name = _dotted(sub)
            if name is None or name in REASON_INTERPOLATIONS:
                continue
            # ข้ามส่วนหัวของ chain ที่ยาวกว่าและประกาศไว้แล้ว (job ของ job.attempts)
            if any(declared.startswith(name + ".") for declared in REASON_INTERPOLATIONS):
                continue
            leaked.append(f"{filename}:{lineno} ใน {fname}() — '{name}'")
    assert not leaked, (
        "transition.reason แทรกค่าที่ยังไม่ได้ประกาศใน REASON_INTERPOLATIONS · "
        "ถ้าเป็นข้อความที่คนพิมพ์ ให้เก็บบนแถวของโดเมนแล้วให้ event ชี้ด้วย subject_id: "
        f"{leaked}"
    )
