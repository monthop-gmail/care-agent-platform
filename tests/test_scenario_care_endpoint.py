"""Care Endpoint foundation — ช่องทาง · presentation · การกระทำต่ออุปกรณ์

ADR-0014 presentation intent เป็นคำขอ ไม่ใช่คำสั่ง
ADR-0015 การกระทำต่ออุปกรณ์เป็น capability ชนิดใหม่
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from core.clock import FakeClock
from core.tenancy import Principal, TenantScope

from care_addons.ap_policy.engine import PolicyDenied, load_policy
from care_addons.care_endpoint import services as endpoint
from care_addons.care_escalation import models as escalation_models
from care_addons.care_escalation import services as jobs
from care_addons.care_patient import services as patients
from care_addons.care_patient.models import CHANNELS
from care_addons.care_routine import services as routines
from tests.conftest import audit_events, notifications, scope_for, setup_patient, system_scope

CARE_ADDONS = pathlib.Path(__file__).resolve().parents[1] / "care_addons"


# ── 0) ช่องทางเป็นชุดปิด และช่องทางที่ไม่รู้จักต้องดัง ────────────────────────


async def test_a_channel_that_is_not_in_the_vocabulary_is_refused_at_write(session, tenant):
    """สะกดผิดต้องพังตอนเขียน ไม่ใช่ตอนส่ง

    🔒 ถ้าปล่อยผ่าน ผลไม่ใช่ error แต่เป็นข้อความที่ไม่ถึงใครโดยไม่มีใครรู้ —
       `_deliver()` เคยตั้ง `delivery_status = "stored"` เงียบ ๆ ให้ทุกช่องทางที่ไม่มี sender
    """
    with pytest.raises(ValueError, match="ไม่รู้จัก"):
        await patients.create_patient(
            session, scope_for(tenant), display_name="คุณยาย", channels=["tvv"]
        )
    await session.rollback()


async def test_delivering_to_an_unknown_channel_raises_instead_of_storing_quietly(session, tenant):
    """แถวเก่าที่หลุดมาก่อนมีชุดปิด ต้องพังให้เห็นตอนส่ง ไม่ใช่เก็บเงียบ"""
    patient, _ = await setup_patient(session, tenant)
    notification = escalation_models.CareNotification(
        tenant_id=tenant,
        patient_id=patient.patient_id,
        audience="patient",
        target_principal_id=patient.patient_id,
        channel="tvv",
        text="ทดสอบ",
    )
    session.add(notification)
    await session.flush()
    with pytest.raises(jobs.UnknownChannel):
        await jobs._deliver(session, scope_for(tenant), notification)
    await session.rollback()


async def test_a_known_channel_without_a_sender_is_still_stored(session, tenant):
    """`app` ไม่มี sender จริงโดยเจตนา — ต่างจากช่องทางที่สะกดผิด"""
    patient, _ = await setup_patient(session, tenant)
    notification = escalation_models.CareNotification(
        tenant_id=tenant,
        patient_id=patient.patient_id,
        audience="patient",
        target_principal_id=patient.patient_id,
        channel="app",
        text="ทดสอบ",
    )
    session.add(notification)
    await session.flush()
    await jobs._deliver(session, scope_for(tenant), notification)
    assert notification.delivery_status == "stored"
    assert "tv" in CHANNELS and "line" in CHANNELS


# ── 1) presentation intent ───────────────────────────────────────────────────


def test_presentation_values_must_come_from_the_closed_set():
    with pytest.raises(ValueError, match="ไม่อยู่ในชุดปิด"):
        escalation_models.validated_presentation({"surface": "billboard"})
    with pytest.raises(ValueError, match="ไม่รู้จักคีย์"):
        escalation_models.validated_presentation({"font_size": "24"})
    assert escalation_models.validated_presentation(None) is None


async def test_quiet_hours_downgrade_what_was_asked_for(session, tenant):
    """intent เป็นเพดานที่ขอ ไม่ใช่สิ่งที่ได้ (ADR-0014 ข้อ 2)

    ขอ overlay + เสียง ตอนกลางดึกสำหรับงาน severity medium แล้วได้ ambient เงียบ ๆ
    เป็นพฤติกรรมที่ถูก ไม่ใช่ bug
    """
    patient, _ = await setup_patient(session, tenant, quiet_hours=("21:00", "07:00"))
    asked = {"surface": "overlay", "speak": True, "response": "required", "dwell": "short"}

    with FakeClock("2026-08-18T17:00:00+00:00"):   # เที่ยงคืนตามเวลาไทย
        from core.clock import now

        quiet = jobs.effective_presentation(
            patient, requested=asked, severity="medium", when=now()
        )
        assert quiet["surface"] == "ambient"
        assert quiet["speak"] is False

    with FakeClock("2026-08-19T03:00:00+00:00"):   # สิบเอ็ดโมงตามเวลาไทย
        from core.clock import now

        awake = jobs.effective_presentation(
            patient, requested=asked, severity="medium", when=now()
        )
        assert awake == asked


async def test_a_medication_reminder_asks_for_an_answer(session, tenant):
    """งานที่ต้องได้คำตอบ ขอ response required และ dwell until_answered"""
    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant)
        await routines.add_routine(
            session,
            scope_for(tenant),
            patient_id=patient.patient_id,
            kind="medication",
            label="ยาเช้า",
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

        outbox = await notifications(session, tenant, patient.patient_id)
        assert outbox[0].presentation["response"] == "required"
        assert outbox[0].presentation["dwell"] == "until_answered"
        assert outbox[0].presented_at is None, "ยังไม่มีใครรายงานว่าวางบนจอ"


async def test_presented_is_not_evidence_and_does_not_close_the_job(session, tenant):
    """🔒 ข้อ 5 ของ ADR-0014 — ไม่มีสถานะไหนกลายเป็น evidence เอง"""
    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant)
        await routines.add_routine(
            session,
            scope_for(tenant),
            patient_id=patient.patient_id,
            kind="medication",
            label="ยาเช้า",
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

        outbox = await notifications(session, tenant, patient.patient_id)
        marked = await jobs.mark_presented(session, scope_for(tenant), outbox[0].id)
        await session.commit()

        assert marked.presented_at is not None
        open_now = await jobs.open_jobs(session, sysscope, patient.patient_id)
        assert open_now, "แสดงบนจอแล้วต้องไม่ปิดงาน"
        assert open_now[0].state == "reminded"
        assert open_now[0].evidence in (None, {}), "presented ต้องไม่กลายเป็น evidence"


def test_no_code_path_turns_delivery_or_presentation_into_evidence():
    """AST scan — กันการไหลจาก delivery/presentation เข้า evidence ตั้งแต่ตอนเขียนโค้ด

    🔒 ADR-0014 ข้อ 5 เขียนว่า "ไม่มีสถานะไหน" ไม่ใช่ "ส่วนใหญ่ไม่" · ข้อแบบนั้น
       ต้องมีตัวตรวจ ไม่ใช่มีแต่ความตั้งใจ
    """
    forbidden = {"delivery_status", "presented_at", "presentation", "presented"}
    leaked: list[str] = []
    for path in sorted(CARE_ADDONS.rglob("*.py")):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Call):
                targets += [kw.value for kw in node.keywords if kw.arg in ("evidence", "evidence_kind")]
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr in ("evidence", "evidence_kind"):
                        targets.append(node.value)
            for expr in targets:
                names = {
                    sub.attr if isinstance(sub, ast.Attribute) else sub.id
                    for sub in ast.walk(expr)
                    if isinstance(sub, ast.Attribute | ast.Name)
                }
                if names & forbidden:
                    leaked.append(f"{path.name}:{expr.lineno} — {sorted(names & forbidden)}")
    assert not leaked, f"delivery/presentation ไหลเข้า evidence: {leaked}"


# ── 2) การกระทำต่ออุปกรณ์ ────────────────────────────────────────────────────


async def test_pause_is_never_blocked_by_approval(session, tenant):
    """หยุดต้องไม่รอใคร — `critical` แต่ override เป็น notify + audit เต็ม (ADR-0015 ข้อ 2)"""
    from care_addons.ap_policy.engine import evaluate

    decision = evaluate("media.playback.pause", actor_type="agent")
    assert decision.audited_exception is True
    assert decision.may_act_now is True, "ถ้าการหยุดต้องรออนุมัติ ตอนต้องหยุดจริงมันจะไม่หยุด"

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        agent = TenantScope(tenant_id=tenant, principal=Principal(type="agent", id="care-agent"))
        await endpoint.pause_media(session, agent, patient.patient_id, trigger="reminder_due")
        await session.commit()

        events = await audit_events(session, tenant, patient.patient_id)
        requested = [e for e in events if e.care_event_type == "care.device.action_requested"]
        assert requested and requested[0].attributes["kind"] == "pause"


def test_resume_is_never_easier_than_pause():
    """เปิดต่อต้องไม่ง่ายกว่าหยุด (ADR-0015 ข้อ 3)"""
    from care_addons.ap_policy.engine import evaluate

    resume = evaluate("media.playback.resume", actor_type="agent")
    assert resume.audited_exception is False, "resume ห้ามเป็นข้อยกเว้นที่ยกเพดาน"
    assert resume.authority != "auto", "ต้องมีร่องรอยเสมอว่าใครสั่งให้จอเล่นต่อ"
    assert load_policy().floor_capabilities["media.playback.resume"] == "notify"


def test_pause_declares_no_undoes_pair():
    """🔒 ADR-0029 กฎ 1a — การเปิดต่อคือการปลุกคน ไม่ใช่การคืนสภาพเดิม

    ถ้าประกาศ `undoes` กฎจะบังคับให้ resume ต้องไม่ยากกว่า pause ซึ่งขัดข้อ 3
    """
    capabilities = load_policy().capabilities
    for name in ("media.playback.pause", "media.playback.cancel", "media.playback.resume"):
        assert "undoes" not in (capabilities[name] or {}), name


async def test_a_device_action_without_a_known_trigger_is_refused(session, tenant):
    """การหยุดจอที่ไม่มีที่มาตอบ audit ไม่ได้"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        with pytest.raises(endpoint.DeviceActionRejected):
            await endpoint.pause_media(
                session, scope_for(tenant), patient.patient_id, trigger="เพราะดูนานเกินไป"
            )
        await session.rollback()


async def test_an_agent_denied_by_the_profile_cannot_act_on_the_device(session, tenant):
    """เพดานยังทำงานกับ capability ชนิดใหม่เหมือนกับชนิดเดิม"""
    from care_addons.ap_policy import profile as profile_module

    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        agent = TenantScope(tenant_id=tenant, principal=Principal(type="agent", id="care-agent"))
        loaded = profile_module.load_profile()
        loaded.deny.append("media.playback.pause")
        try:
            with pytest.raises(PolicyDenied):
                await endpoint.pause_media(
                    session, agent, patient.patient_id, trigger="reminder_due"
                )
        finally:
            loaded.deny.remove("media.playback.pause")
        await session.rollback()
