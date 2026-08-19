"""Scenario S11 — คิวรออนุมัติ: สิ่งที่ AI เสนอ ต้องมีคนตัดสินเสมอ

    ข้อเสนอเรื่องยาไม่หายไปไหนถ้าผู้ดูแลไม่อยู่ตอนนั้น แต่ก็ **ไม่กลายเป็นคำสั่งจริงเองเพราะเวลาผ่านไป**
    เทสในไฟล์นี้คือหลักฐานว่ากติกาของ approval/v1 ถูกบังคับด้วยโค้ด ไม่ใช่ด้วยความตั้งใจ
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from care_addons.ap_approval import services as approvals
from care_addons.ap_policy.engine import evaluate
from care_addons.ap_tenancy.clock import FakeClock
from care_addons.ap_tenancy.services import Principal
from care_addons.care_medication import services as meds
from tests.conftest import audit_events, scope_for, setup_patient

AGENT = Principal(type="agent", id="care-agent")
DAUGHTER = {"type": "human", "id": "user-daughter", "display_name": "ลูกสาว"}
SON = {"type": "human", "id": "user-son", "display_name": "ลูกชาย"}


def agent_scope(tenant_id: str):
    from care_addons.ap_tenancy.services import TenantScope

    return TenantScope(tenant_id=tenant_id, principal=AGENT)


async def _let_agent_read_the_chart(session, tenant_id, patient_id):
    """agent ก็ต้องมี consent เหมือนคน — ไม่มีสิทธิ์พิเศษเพราะเป็นเครื่อง (ADR-0007)"""
    from care_addons.ap_tenancy import services as tenancy

    await tenancy.grant_consent(
        session,
        scope_for(tenant_id),
        subject_id=patient_id,
        grantee=AGENT,
        scopes=["care.manage"],
        granted_by=Principal(type="human", id="user-1"),
        authority_basis="ผู้ดูแลหลักมอบหมายให้ผู้ช่วยช่วยจดคำสั่งหมอ",
    )


async def _propose(session, tenant_id, patient_id, *, name="Donepezil"):
    await _let_agent_read_the_chart(session, tenant_id, patient_id)
    return await meds.propose_version(
        session,
        agent_scope(tenant_id),
        patient_id=patient_id,
        name=name,
        schedule=[{"time": "20:00", "relation_to_meal": "bedtime", "dose": "1 tablet"}],
        instruction_source="doctor_instruction",
        prescribed_by={"doctor_name": "หมอ A"},
    )


async def test_proposal_creates_a_pending_request(session, tenant):
    """agent เสนอยา → มีคำขอรออยู่ในคิว พร้อมข้อมูลพอให้คนตัดสินได้"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        version = await _propose(session, tenant, patient.patient_id)
        await session.commit()

        scope = scope_for(tenant)
        [req] = await approvals.pending_requests(session, scope)
        assert req.subject_id == version.version_id
        assert req.capability == "medication.regimen.write"
        # policy ของโดเมนนี้มีเพดาน — ยาต้องเป็นคำสั่งของคนเสมอ (ADR-0006)
        assert req.authority_required == "human_command_required"
        assert req.requested_by["type"] == "agent"
        assert req.proposed["name"] == "Donepezil"
        assert req.expires_at is None   # ค้างได้ตลอดกาล


async def test_time_never_approves_anything(session, tenant):
    """คำขอที่เลยกำหนดกลายเป็น expired — ยาไม่ถูกเปลี่ยน ไม่ใช่ถูกอนุมัติ"""
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant)
        version = await _propose(session, tenant, patient.patient_id)
        scope = scope_for(tenant)
        req = await approvals.request_approval(
            session,
            scope,
            decision=evaluate("medication.regimen.write"),
            subject_type="artifact",
            subject_id=version.version_id,
            summary="คำขอที่มีกำหนดหมดอายุ",
            requested_by=AGENT.as_dict(),
            expires_in=timedelta(hours=6),
        )
        await session.commit()

        clock.advance(hours=7)
        assert await approvals.expire_overdue(session, scope) == 1
        await session.commit()

        await session.refresh(req)
        assert req.state == "expired"
        assert (
            await approvals.effective_approval(
                session, scope, subject_type="artifact", subject_id=version.version_id
            )
            is None
        )
        # ยายังไม่มีผล — เวลาผ่านไปทำให้ระบบ "หยุด" ไม่ใช่ "ลงมือ"
        assert await meds.current_regimen(session, scope, patient.patient_id) == []


async def test_approve_makes_the_regimen_real_under_the_deciders_name(session, tenant):
    """คนกดอนุมัติ → version เป็น active และประวัติชี้ตัวคนที่ตัดสิน ไม่ใช่ agent ที่เสนอ"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        version = await _propose(session, tenant, patient.patient_id)
        await session.commit()

        scope = scope_for(tenant)
        [req] = await approvals.pending_requests(session, scope)
        approval = await approvals.decide(
            session,
            scope,
            request_id=req.request_id,
            decision="APPROVE",
            reason="คุยกับหมอแล้ว ยืนยันตามที่สั่ง",
            authority=DAUGHTER,
        )
        await session.commit()

        await session.refresh(version)
        assert version.status == "active"
        assert version.confirmed_by["id"] == "user-daughter"
        assert approval.decision == "APPROVE"

        regimen = await meds.current_regimen(session, scope, patient.patient_id)
        assert [r.name for r in regimen] == ["Donepezil"]

        # 🔒 ทุก APPROVE ต้องมี GOVERNANCE_DECISION คู่กัน (approval/v1 guarantee)
        events = await audit_events(session, tenant)
        decisions = [
            e for e in events
            if e.event_type == "GOVERNANCE_DECISION" and e.subject_id == approval.approval_id
        ]
        assert len(decisions) == 1
        assert decisions[0].attributes["authority_id"] == "user-daughter"


async def test_reject_leaves_the_regimen_untouched(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        version = await _propose(session, tenant, patient.patient_id)
        await session.commit()

        scope = scope_for(tenant)
        [req] = await approvals.pending_requests(session, scope)
        await approvals.decide(
            session,
            scope,
            request_id=req.request_id,
            decision="REJECT",
            reason="ยานี้เคยแพ้ ต้องถามหมอก่อน",
            authority=DAUGHTER,
        )
        await session.commit()

        await session.refresh(version)
        assert version.status == "proposed"
        assert await meds.current_regimen(session, scope, patient.patient_id) == []


async def test_changing_your_mind_is_a_new_approval_that_cites_the_old(session, tenant):
    """decision เป็น immutable — เปลี่ยนใจ = ใบใหม่ที่ supersedes ใบเดิม"""
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant)
        version = await _propose(session, tenant, patient.patient_id)
        await session.commit()
        scope = scope_for(tenant)
        [req] = await approvals.pending_requests(session, scope)

        first = await approvals.decide(
            session, scope, request_id=req.request_id,
            decision="REQUIRE_CHANGES", reason="ขอเวลาที่ชัดกว่านี้", authority=DAUGHTER,
        )
        await session.commit()
        clock.advance(hours=1)
        second = await approvals.decide(
            session, scope, request_id=req.request_id,
            decision="APPROVE", reason="หมอยืนยันเวลาแล้ว", authority=DAUGHTER,
        )
        await session.commit()

        assert second.supersedes == first.approval_id
        assert first.decision == "REQUIRE_CHANGES"   # ใบเดิมไม่ถูกแก้
        await session.refresh(version)
        assert version.status == "active"


async def test_requester_cannot_decide_its_own_request(session, tenant):
    """no agent has total authority — ผู้ยื่นตัดสินคำขอของตัวเองไม่ได้"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)   # user-1 เป็นทั้งผู้ยื่นและผู้จะกดอนุมัติ
        version = await meds.propose_version(
            session,
            scope,
            patient_id=patient.patient_id,
            name="Donepezil",
            schedule=[{"time": "20:00", "relation_to_meal": "bedtime", "dose": "1 tablet"}],
            instruction_source="doctor_instruction",
        )
        await session.commit()
        [req] = await approvals.pending_requests(session, scope)

        with pytest.raises(approvals.ApprovalRejected, match="ตัดสินคำขอของตัวเอง"):
            await approvals.decide(
                session, scope, request_id=req.request_id,
                decision="APPROVE", reason="ตัวเองอนุมัติเอง", authority={"type": "human", "id": "user-1"},
            )
        await session.rollback()
        await session.refresh(version)
        assert version.status == "proposed"


async def test_only_humans_decide(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        await _propose(session, tenant, patient.patient_id)
        await session.commit()
        scope = scope_for(tenant)
        [req] = await approvals.pending_requests(session, scope)

        with pytest.raises(approvals.ApprovalRejected, match="คนเท่านั้น"):
            await approvals.decide(
                session, scope, request_id=req.request_id,
                decision="APPROVE", reason="agent อนุมัติเอง",
                authority={"type": "agent", "id": "another-agent"},
            )
        await session.rollback()


async def test_decision_without_a_reason_is_rejected(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        await _propose(session, tenant, patient.patient_id)
        await session.commit()
        scope = scope_for(tenant)
        [req] = await approvals.pending_requests(session, scope)

        with pytest.raises(approvals.ApprovalRejected, match="reason"):
            await approvals.decide(
                session, scope, request_id=req.request_id,
                decision="APPROVE", reason="   ", authority=DAUGHTER,
            )
        with pytest.raises(approvals.ApprovalRejected, match="ชุดปิด"):
            await approvals.decide(
                session, scope, request_id=req.request_id,
                decision="AUTO_APPROVE", reason="ระบบอนุมัติให้", authority=DAUGHTER,
            )
        await session.rollback()


async def test_direct_confirm_closes_the_pending_request_without_approving_it(session, tenant):
    """ผู้ดูแลกดยืนยันตรง ๆ = เรื่องจบไปทางอื่น คำขอกลายเป็น withdrawn ไม่ใช่ approved"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        version = await _propose(session, tenant, patient.patient_id)
        await session.commit()

        scope = scope_for(tenant)
        [req] = await approvals.pending_requests(session, scope)
        await meds.confirm_version(
            session, scope, version.version_id,
            confirmed_by=Principal(type="human", id="user-son", display_name="ลูกชาย"),
        )
        await session.commit()

        await session.refresh(req)
        assert req.state == "withdrawn"
        assert await approvals.pending_requests(session, scope) == []
        # ไม่มีใบอนุมัติเกิดขึ้นจาก path นี้
        assert (
            await approvals.effective_approval(
                session, scope, subject_type="artifact", subject_id=version.version_id
            )
            is None
        )


async def test_requests_are_not_visible_across_tenants(session, tenant):
    from care_addons.ap_tenancy import services as tenancy
    from tests.conftest import use_tenant

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        await _propose(session, tenant, patient.patient_id)
        await session.commit()

        other = f"{tenant}-other"
        await tenancy.create_tenant(session, other, "อีกครอบครัว")
        await session.commit()
        await use_tenant(session, other)
        assert await approvals.pending_requests(session, scope_for(other)) == []
        await use_tenant(session, tenant)
