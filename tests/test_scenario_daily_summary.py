"""Scenario S12 — สรุปประจำวันถึงผู้ดูแล (M3)

    ตอนสองทุ่ม **ตามเวลาบ้านของผู้ป่วย** ผู้ดูแลได้สรุปว่าวันนี้เกิดอะไรขึ้นบ้าง
    เป็นข้อเท็จจริงที่วัดได้ล้วน ๆ — ไม่มีประโยคไหนตีความอาการ (ADR-0004 ข้อ 4)
"""

from __future__ import annotations

from datetime import date, timedelta

from core.clock import FakeClock

from care_addons.ap_approval import services as approvals
from care_addons.ap_policy.engine import evaluate
from care_addons.care_escalation import services as jobs
from care_addons.care_orchestrator import services as orchestrator
from care_addons.care_orchestrator import summary_policy
from care_addons.care_routine import services as routines
from tests.conftest import notifications, scope_for, setup_patient, system_scope

DAY = date(2026, 8, 19)


async def _seed_day(session, tenant_id, *, timezone="Asia/Bangkok"):
    """กิจวัตรสามอย่างของวัน: ยาเช้า มื้อเที่ยง เดินเย็น"""
    patient, caregiver = await setup_patient(session, tenant_id, timezone=timezone)
    admin = scope_for(tenant_id)
    for kind, label, at in (
        ("medication", "ยาเช้า หลังอาหาร", "08:00"),
        ("meal", "มื้อเที่ยง", "12:00"),
        ("activity", "เดินรอบบ้าน", "17:00"),
    ):
        await routines.add_routine(
            session,
            admin,
            patient_id=patient.patient_id,
            kind=kind,
            label=label,
            scheduled_time=at,
            severity="medium",
        )
    await session.commit()
    return patient, caregiver


async def test_summary_counts_only_what_was_actually_confirmed(session, tenant):
    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient, _ = await _seed_day(session, tenant)
        sysscope = system_scope(tenant)
        created = await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()
        assert len(created) == 3

        # ยาเช้า: ยืนยันแล้ว
        clock.set("2026-08-19T01:00:00+00:00")
        await jobs.run_due_jobs(session, sysscope)
        med = next(j for j in created if j.source_kind == "medication")
        await jobs.acknowledge(session, scope_for(tenant, patient.patient_id), med.care_job_id)
        await session.commit()

        # มื้อเที่ยง: เงียบจนพลาด
        clock.set("2026-08-19T05:00:00+00:00")
        await jobs.run_due_jobs(session, sysscope)
        clock.advance(minutes=45)
        await jobs.run_due_jobs(session, sysscope)
        clock.advance(minutes=45)
        await jobs.run_due_jobs(session, sysscope)
        clock.advance(minutes=45)          # ครบ 3 ครั้งแล้วยังเงียบ → missed → escalate
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

        clock.set("2026-08-19T13:05:00+00:00")   # 20:05 ตามเวลาไทย
        facts = await orchestrator.build_facts(session, sysscope, patient, DAY)

        assert facts["buckets"]["medication"]["done"] == 1
        assert facts["buckets"]["medication"]["missed"] == 0
        assert facts["buckets"]["meals"]["missed"] == 1
        # เดินเย็นถึงกำหนดแล้วแต่ยังไม่มีใครยืนยัน — เป็น "ยังไม่ยืนยัน" ไม่ใช่ "ทำแล้ว"
        assert facts["buckets"]["activities"]["done"] == 0
        # ค้าง = ถึงกำหนดแล้วยังไม่มีใครปิด — มื้อเที่ยงถูกส่งต่อให้ผู้ดูแลแล้วแต่ยังไม่มีใครรับเรื่อง
        assert {s["label"] for s in facts["stalled_tasks"]} == {"มื้อเที่ยง", "เดินรอบบ้าน"}


async def test_summary_text_reports_facts_and_says_so(session, tenant):
    with FakeClock("2026-08-19T13:05:00+00:00"):
        patient, _ = await _seed_day(session, tenant)
        sysscope = system_scope(tenant)
        facts = await orchestrator.build_facts(session, sysscope, patient, DAY)
        text = orchestrator.render(patient, facts)

        assert "ไม่ได้ยืนยันไม่ได้แปลว่าไม่ได้ทำ" in text
        # 🔒 ห้ามมีคำที่เป็นการตีความอาการหรือคำแนะนำทางการแพทย์
        for banned in ("อาการ", "น่าจะ", "ควรพาไป", "สับสน", "แย่ลง", "ดีขึ้น", "วินิจฉัย"):
            assert banned not in text, f"สรุปมีคำที่เป็นการตีความ: {banned}"


async def test_summary_is_sent_once_a_day(session, tenant):
    with FakeClock("2026-08-19T13:05:00+00:00") as clock:
        patient, caregiver = await _seed_day(session, tenant)
        sysscope = system_scope(tenant)

        first = await orchestrator.send_daily_summary(session, sysscope, patient)
        await session.commit()
        assert first is not None
        assert first.recipients == 1
        assert first.sent_at is not None

        again = await orchestrator.send_daily_summary(session, sysscope, patient)
        await session.commit()
        assert again is None      # เรียกซ้ำได้ แต่ไม่ส่งซ้ำ

        sent = await notifications(session, tenant, patient.patient_id, audience="caregiver")
        summaries = [n for n in sent if n.text.startswith("สรุปวันที่")]
        assert len(summaries) == 1
        assert summaries[0].target_principal_id == caregiver.principal_id

        # วันใหม่ = สรุปใบใหม่
        clock.set("2026-08-20T13:05:00+00:00")
        tomorrow = await orchestrator.send_daily_summary(session, sysscope, patient)
        await session.commit()
        assert tomorrow is not None
        assert tomorrow.local_date == date(2026, 8, 20)


async def test_send_time_follows_the_patients_timezone(session, tenant):
    """20:00 ของบ้านผู้ป่วย ไม่ใช่ 20:00 ของ data center"""
    assert summary_policy.send_at().hour == 20

    with FakeClock("2026-08-19T11:00:00+00:00") as clock:   # 18:00 ไทย — ยังไม่ถึงเวลา
        patient, _ = await _seed_day(session, tenant)
        sysscope = system_scope(tenant)
        assert await orchestrator.due_for_summary(session, sysscope) == []

        clock.set("2026-08-19T13:30:00+00:00")              # 20:30 ไทย — ถึงเวลาแล้ว
        due = await orchestrator.due_for_summary(session, sysscope)
        assert [p.patient_id for p in due] == [patient.patient_id]

        result = await orchestrator.run_daily_summaries(session, sysscope)
        await session.commit()
        assert result["summaries"] == 1
        assert await orchestrator.due_for_summary(session, sysscope) == []


async def test_summary_shows_what_is_waiting_for_a_human(session, tenant):
    """เรื่องที่รอคนตัดสินต้องโผล่ในสรุป ไม่งั้นคำขอจะค้างอยู่เงียบ ๆ ตลอดไป"""
    with FakeClock("2026-08-19T13:05:00+00:00"):
        patient, _ = await _seed_day(session, tenant)
        sysscope = system_scope(tenant)
        admin = scope_for(tenant)
        from care_addons.care_medication import services as meds

        await meds.propose_version(
            session,
            admin,
            patient_id=patient.patient_id,
            name="Donepezil",
            schedule=[{"time": "20:00", "relation_to_meal": "bedtime", "dose": "1 tablet"}],
            instruction_source="doctor_instruction",
        )
        await session.commit()

        row = await orchestrator.send_daily_summary(session, sysscope, patient)
        await session.commit()
        assert len(row.facts["awaiting_decision"]) == 1
        assert "รอคุณตัดสิน 1 เรื่อง" in row.text


async def test_daily_run_expires_overdue_approvals_without_approving_them(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        await _seed_day(session, tenant)
        sysscope = system_scope(tenant)
        admin = scope_for(tenant)
        req = await approvals.request_approval(
            session,
            admin,
            decision=evaluate("medication.regimen.write"),
            subject_type="artifact",
            subject_id="mv-000000000000",
            summary="คำขอที่มีกำหนด",
            requested_by={"type": "agent", "id": "care-agent"},
            expires_in=timedelta(hours=2),
        )
        await session.commit()

        clock.set("2026-08-19T13:30:00+00:00")
        result = await orchestrator.run_daily_summaries(session, sysscope)
        await session.commit()
        assert result["expired_approvals"] == 1

        await session.refresh(req)
        assert req.state == "expired"
        assert await approvals.pending_requests(session, admin) == []


async def test_summary_works_on_jobs_loaded_fresh_from_the_database(session, tenant):
    """เวลาที่อ่านกลับมาจาก DB อาจไม่มี timezone ติดมา (sqlite) — สรุปต้องไม่พังเพราะเรื่องนี้

    เทสอื่นใช้ object ที่ยังอยู่ใน session เดิมซึ่งมี tzinfo ครบ จึงมองไม่เห็นปัญหานี้
    ของจริงที่ worker เจอคือแถวที่เพิ่งโหลดขึ้นมาใหม่
    """
    with FakeClock("2026-08-19T13:05:00+00:00"):
        patient, _ = await _seed_day(session, tenant)
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        session.expunge_all()          # ทิ้ง identity map — บังคับให้โหลดใหม่จาก DB จริง
        reloaded = await _reload_patient(session, sysscope, patient.patient_id)
        row = await orchestrator.send_daily_summary(session, sysscope, reloaded)
        await session.commit()
        assert row is not None
        assert row.facts["counted_jobs"] == 3


async def _reload_patient(session, scope, patient_id):
    from care_addons.care_patient.services import get_patient

    return await get_patient(session, scope, patient_id, required_scope="care.manage")
