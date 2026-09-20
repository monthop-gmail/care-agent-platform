"""Scenario — เจ้าของข้อมูลใช้สิทธิ์ขอให้ลบ (ADR-0012 · dec-d1302f96 ทางเลือก A)

หลังลบแล้ว trail ต้องยังตอบได้ว่า **เกิดอะไรขึ้นเมื่อไร** แต่ตอบไม่ได้ว่า **ของใคร**
"""

from __future__ import annotations

import pytest
from core.clock import FakeClock
from core.tenancy import Principal, TenantScope

from care_addons.ap_audit.models import ApAuditEvent
from care_addons.ap_policy.engine import PolicyDenied
from care_addons.care_medication import services as meds
from care_addons.care_patient import erasure
from care_addons.care_routine import services as routines
from tests.conftest import scope_for, setup_patient

REQUEST = "PDPA-2026-0007"


async def _patient_with_history(session, tenant, *, name="ยาความดัน Amlodipine"):
    patient, caregiver = await setup_patient(session, tenant)
    scope = scope_for(tenant)
    await routines.add_routine(
        session,
        scope,
        patient_id=patient.patient_id,
        kind="medication",
        label=name,
        scheduled_time="08:00",
        severity="medium",
    )
    await meds.propose_version(
        session,
        scope,
        patient_id=patient.patient_id,
        name=name,
        schedule=[{"time": "08:00", "relation_to_meal": "after_meal", "dose": "1 เม็ด"}],
        instruction_source="doctor_instruction",
        prescribed_by={"doctor_name": "หมอ A", "specialty": "cardiology"},
    )
    await session.commit()
    return patient, caregiver


SECOND_HUMAN = {"type": "human", "id": "user-2", "display_name": "หัวหน้าทีมดูแล"}


async def _erase_with_two_people(session, tenant, patient_id, *, request_ref=REQUEST):
    """ทางจริงของการลบ — คนหนึ่งยื่น อีกคนอนุมัติ แล้ว applier ถึงจะลบ (ADR-0013)"""
    from care_addons.ap_approval import services as approvals

    request = await erasure.request_erasure(
        session, scope_for(tenant), patient_id, request_ref=request_ref
    )
    return await approvals.decide(
        session,
        scope_for(tenant, principal_id="user-2"),
        request_id=request.request_id,
        decision="APPROVE",
        reason="ตรวจใบคำขอแล้วถูกต้อง",
        authority=SECOND_HUMAN,
    )


async def _rows_left(session, tenant, patient_id) -> dict[str, int]:
    from core.db import Base
    from sqlalchemy import func, select

    left = {}
    for table_name, column in erasure.erasable_tables():
        table = Base.metadata.tables[table_name]
        count = await session.scalar(
            select(func.count())
            .select_from(table)
            .where(table.c.tenant_id == tenant, table.c[column] == patient_id)
        )
        if count:
            left[table_name] = count
    return left


async def test_erasure_deletes_the_bridge_and_leaves_the_trail(session, tenant):
    """ทางเลือก A — ลบแถวของโดเมน · audit อยู่ต่อ · ตัวตนตามกลับไม่ได้"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_history(session, tenant)
        before = await _rows_left(session, tenant, patient.patient_id)
        assert before, "ต้องมีข้อมูลให้ลบจริง ไม่งั้นเทสนี้ผ่านฟรี"

        await _erase_with_two_people(session, tenant, patient.patient_id)
        await session.commit()

        assert await _rows_left(session, tenant, patient.patient_id) == {}

        # trail ยังอยู่ — และยังตอบได้ว่าเกิดอะไรขึ้น
        from sqlalchemy import select

        events = (
            await session.execute(
                select(ApAuditEvent).where(ApAuditEvent.tenant_id == tenant).order_by(
                    ApAuditEvent.occurred_at, ApAuditEvent.sequence
                )
            )
        ).scalars().all()
        assert events
        erased = [e for e in events if e.care_event_type == "care.patient.erased"]
        assert len(erased) == 1
        assert erased[0].attributes["erased_rows"] > 0
        assert erased[0].attributes["subject_ref"] == REQUEST

        # 🔒 แต่ไม่มีใครตามกลับไปหาตัวตนได้ — ชื่อยาและชื่อคนไม่เหลืออยู่ใน trail เลย
        for event in events:
            blob = f"{event.attributes} {event.transition} {event.actor} {event.evidence}"
            assert "Amlodipine" not in blob
            assert "ลูกสาว" not in blob


async def test_erasure_is_not_recorded_as_withdrawing_consent(session, tenant):
    """เงื่อนไขข้อ 3 ของ dec-d1302f96 — คนละการกระทำ คนละผลทางกฎหมาย

    ถ้า implement ทับกัน บันทึกจะบอกว่าเจ้าของข้อมูลถอนความยินยอม ทั้งที่เขาขอให้ลบตัวตน
    และตรวจย้อนไม่เจอ เพราะบันทึกดูปกติทุกอย่าง
    """
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_history(session, tenant)
        await _erase_with_two_people(session, tenant, patient.patient_id)
        await session.commit()

        from sqlalchemy import select

        kinds = (
            await session.execute(
                select(ApAuditEvent.event_type).where(ApAuditEvent.tenant_id == tenant)
            )
        ).scalars().all()
        assert "CONSENT_REVOKED" not in kinds, "erasure ต้องไม่ถูกบันทึกเป็นการถอนความยินยอม"


async def test_erasure_never_touches_the_other_patient_in_the_house(session, tenant):
    """บ้านหนึ่งมีผู้ป่วยสองคนได้ — คำขอของคนหนึ่งไม่ใช่ของอีกคน"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        first, _ = await _patient_with_history(session, tenant)
        second, _ = await _patient_with_history(session, tenant, name="ยาเบาหวาน Metformin")

        await _erase_with_two_people(session, tenant, first.patient_id)
        await session.commit()

        assert await _rows_left(session, tenant, first.patient_id) == {}
        assert await _rows_left(session, tenant, second.patient_id), "ของอีกคนต้องอยู่ครบ"


async def test_an_agent_can_never_erase_a_person(session, tenant):
    """`patient.data.erase` อยู่ใน tools.deny — เพดานปฏิเสธก่อนถึงโค้ดด้วยซ้ำ"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_history(session, tenant)
        agent_scope = TenantScope(
            tenant_id=tenant, principal=Principal(type="agent", id="care-agent")
        )
        with pytest.raises(PolicyDenied):
            await erasure.request_erasure(
                session, agent_scope, patient.patient_id, request_ref=REQUEST
            )
        await session.rollback()


async def test_a_service_account_cannot_erase_either(session, tenant):
    """orchestrator ที่เดิน closed loop เองก็สั่งลบไม่ได้ — ต้องเป็นคนเท่านั้น"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_history(session, tenant)
        service_scope = TenantScope(
            tenant_id=tenant, principal=Principal(type="service", id="care-orchestrator")
        )
        with pytest.raises(erasure.ErasureRefused):
            await erasure.request_erasure(
                session, service_scope, patient.patient_id, request_ref=REQUEST
            )
        await session.rollback()


async def test_erasure_requires_a_reference_that_is_a_pointer_not_a_sentence(session, tenant):
    """audit เก็บตัวชี้ ไม่ใช่เนื้อหา — เลขใบคำขอผ่าน คำบรรยายไม่ผ่าน (ADR-0011)"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_history(session, tenant)
        scope = scope_for(tenant)
        with pytest.raises(ValueError):
            await erasure.request_erasure(session, scope, patient.patient_id, request_ref="")
        with pytest.raises(ValueError):
            await erasure.request_erasure(
                session,
                scope,
                patient.patient_id,
                request_ref="ลูกสาวโทรมาขอให้ลบข้อมูลของคุณยาย",
            )
        await session.rollback()


def test_every_table_that_holds_a_patient_id_is_erased():
    """ตารางใหม่ที่ใครเพิ่มพรุ่งนี้ต้องเข้าข่ายเอง ไม่ต้องมีใครมาลงทะเบียน

    🔒 ข้อนี้คือเงื่อนไขข้อ 1 ของ dec-d1302f96 — A ตัดสะพานเส้นเดียว ถ้ายังมีตาราง
       ที่ถือ patient_id อยู่นอกคำสั่งลบ การตัดสะพานนั้นไม่เปลี่ยนอะไรเลย
    """
    from core.db import Base

    covered = {name for name, _ in erasure.erasable_tables()}
    missing = [
        table.name
        for table in Base.metadata.tables.values()
        if "patient_id" in table.columns
        and "tenant_id" in table.columns
        and table.name not in covered
        and table.name != "ap_audit_event"
    ]
    assert not missing, f"ตารางที่ถือ patient_id แต่คำสั่งลบไม่ครอบ: {missing}"
    assert "ap_audit_event" not in covered, "audit เป็น append-only ห้ามลบ"
    assert "ap_consent_grant" in covered, "ใบยินยอมของผู้ป่วยต้องถูกลบ ไม่ใช่ถูกเพิกถอน"


async def test_a_pending_request_deletes_nothing(session, tenant):
    """ยื่นแล้วยังไม่มีใครอนุมัติ = ยังไม่มีอะไรหาย (ADR-0013)

    🔒 ข้อนี้คือเหตุผลที่ route ตอบ 202 ไม่ใช่ 200 — "รับเรื่องแล้ว" ไม่ใช่ "ลบแล้ว"
    """
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_history(session, tenant)
        request = await erasure.request_erasure(
            session, scope_for(tenant), patient.patient_id, request_ref=REQUEST
        )
        await session.commit()

        assert request.state == "pending"
        assert await _rows_left(session, tenant, patient.patient_id), "ยังไม่อนุมัติ ต้องยังอยู่ครบ"


async def test_the_person_who_asked_cannot_approve_their_own_request(session, tenant):
    """คนเดียวลบคนทั้งคนไม่ได้ — ต้องมีคนที่สอง (approval/v1 invariant)

    การลบไม่มี undo · คนเดียวที่พลาดหรือถูกกดดัน ทำลายบันทึกของคนหนึ่งคนถาวรได้
    ซึ่งเป็นรูปความล้มเหลวเดียวกับที่เราไม่ยอมให้ agent ทำ
    """
    from care_addons.ap_approval import services as approvals

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_history(session, tenant)
        request = await erasure.request_erasure(
            session, scope_for(tenant), patient.patient_id, request_ref=REQUEST
        )
        with pytest.raises(approvals.ApprovalRejected):
            await approvals.decide(
                session,
                scope_for(tenant),
                request_id=request.request_id,
                decision="APPROVE",
                reason="อนุมัติเอง",
                authority={"type": "human", "id": "user-1"},
            )
        await session.rollback()


async def test_erasing_without_an_approval_is_refused(session, tenant):
    """กฎสองคนอยู่ติดกับการลบ ไม่ใช่ติดกับหน้าจอ — เรียกฟังก์ชันตรง ๆ ก็ผ่านไม่ได้"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_history(session, tenant)
        with pytest.raises(erasure.ErasureRefused):
            await erasure.erase_patient(
                session,
                scope_for(tenant),
                patient.patient_id,
                request_ref=REQUEST,
                approval_id="apv-ไม่มีจริง",
            )
        await session.rollback()


async def test_a_rejected_request_deletes_nothing(session, tenant):
    """ปฏิเสธแล้วต้องไม่มีอะไรหาย และใบต้องไม่กลายเป็นอนุมัติทีหลัง"""
    from care_addons.ap_approval import services as approvals

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_history(session, tenant)
        request = await erasure.request_erasure(
            session, scope_for(tenant), patient.patient_id, request_ref=REQUEST
        )
        approval = await approvals.decide(
            session,
            scope_for(tenant, principal_id="user-2"),
            request_id=request.request_id,
            decision="REJECT",
            reason="ใบคำขอยังไม่ครบเอกสาร",
            authority=SECOND_HUMAN,
        )
        await session.commit()

        assert await _rows_left(session, tenant, patient.patient_id), "ถูกปฏิเสธ ต้องยังอยู่ครบ"
        with pytest.raises(erasure.ErasureRefused):
            await erasure.erase_patient(
                session,
                scope_for(tenant),
                patient.patient_id,
                request_ref=REQUEST,
                approval_id=approval.approval_id,
            )
        await session.rollback()


async def test_the_approval_that_authorised_the_erasure_is_erased_too(session, tenant):
    """ใบอนุมัติถือ `reason` ที่คนพิมพ์ — `approval/v1` บังคับ required + minLength 1

    กฎ leaf ผูก `approval/v1` ตั้งแต่ semantics 1.5 และข้อ 3 ถามว่ากติกาการลบอยู่ชั้นไหน
    คำตอบของเราคือชั้นแถวของโดเมน ซึ่งแปลว่า erasure ต้องลบมันจริง ไม่ใช่แค่เขียนว่าลบได้

    🔒 รวมถึงใบที่อนุมัติการลบครั้งนี้เอง · หลักฐานว่ามีคนสองคนไม่ได้หายไปด้วย
       เพราะมันอยู่ใน audit เป็นตัวชี้ ไม่ใช่อยู่ในแถวที่ถูกลบ (ADR-0011)
    """
    from sqlalchemy import func, select

    from care_addons.ap_approval.models import ApApproval, ApApprovalRequest

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await _patient_with_history(session, tenant)
        await _erase_with_two_people(session, tenant, patient.patient_id)
        await session.commit()

        for model in (ApApproval, ApApprovalRequest):
            left = await session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == tenant)
            )
            assert left == 0, f"{model.__tablename__} ยังเหลือแถวที่ถือข้อความของคน"

        # หลักฐานสองคนยังอยู่ใน audit — ผู้ยื่นกับผู้ตัดสินเป็นคนละคน
        events = (
            await session.execute(
                select(ApAuditEvent).where(ApAuditEvent.tenant_id == tenant)
            )
        ).scalars().all()
        asked = [e for e in events if e.event_type == "TASK_ASSIGNED"]
        decided = [e for e in events if e.event_type == "GOVERNANCE_DECISION" and e.attributes]
        approved = [e for e in decided if e.attributes.get("decision") == "APPROVE"]
        assert asked and approved
        assert asked[-1].actor["id"] != approved[-1].attributes["authority_id"]
