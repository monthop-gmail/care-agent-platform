"""กำหนดตายของงานที่ส่งออกไปที่อุปกรณ์ — ADR-0016

ตอบ task-9f541390 · โดเมนตั้ง อุปกรณ์บังคับตาม · ไม่มีตัวเลขไหนในใบนี้ที่อธิบายไม่ได้
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from core.clock import FakeClock

from adapters.care_tv import inbound, runtime, sender
from adapters.care_tv.prompts import PromptBook, StalePrompt
from adapters.care_tv.transport import Envelope, InMemoryQueue, PollingTransport
from care_addons.care_endpoint import expiry
from care_addons.care_endpoint import services as endpoint
from care_addons.care_escalation import services as jobs
from care_addons.care_routine import services as routines
from tests.conftest import notifications, scope_for, setup_patient, system_scope

# ── A) ทะเบียนกฎ — ทุกชนิดต้องอธิบายตัวเองได้ ────────────────────────────────


def test_every_class_states_a_care_reason_not_just_a_number():
    """🔒 ข้อบังคับของใบงาน — ค่าต้องอธิบายด้วยความหมายของงาน ไม่ใช่เลขลอย ๆ"""
    for name, rule in expiry.CLASSES.items():
        assert len(rule.reason) > 40, f"{name} ไม่มีเหตุผลเชิงการดูแลที่อ่านได้"
        if rule.rule == expiry.SHORT_FRESHNESS:
            assert rule.minutes and rule.ceiling_minutes, f"{name} ต้องประกาศเพดาน"
            assert rule.ceiling_minutes >= rule.minutes


def test_a_class_outside_the_registry_raises_instead_of_getting_no_deadline():
    with pytest.raises(expiry.UnknownExpiryClass):
        expiry.deadline_for("whatever_feels_right")


def test_only_a_declared_never_rule_produces_no_deadline():
    """🔒 `None` ต้องมาจากกฎที่เขียนเหตุผลไว้ ไม่ใช่จากการหาค่าไม่เจอ"""
    nevers = [n for n, r in expiry.CLASSES.items() if r.rule == expiry.NEVER]
    assert nevers == ["caregiver_help"]
    assert expiry.deadline_for("caregiver_help") is None
    assert "ความเงียบ" in expiry.CLASSES["caregiver_help"].reason
    for name in expiry.CLASSES:
        if name not in nevers:
            assert expiry.deadline_for(name, due_at=datetime.now(ZoneInfo("UTC"))) is not None


# ── B) ค่าที่ใช้มาจากของที่ทีมดูแลตั้งไว้แล้ว ไม่ใช่เลขที่เราคิดขึ้น ──────────


def test_the_work_window_comes_from_grace_minutes_that_the_care_team_already_sets():
    """🔒 `grace_minutes` มีในฐานข้อมูลตั้งแต่ schema แรกและยังไม่มีใครอ่าน · ใบนี้ให้มันมีความหมาย

    เปลี่ยนค่าที่ทีมดูแลตั้ง แล้วกำหนดตายต้องขยับตาม — ถ้าไม่ขยับ แปลว่าเราฝังเลขไว้เอง
    """
    due = datetime(2026, 9, 28, 8, 0, tzinfo=ZoneInfo("UTC"))
    tight = expiry.deadline_for("routine_prompt", due_at=due, grace_minutes=10)
    loose = expiry.deadline_for("routine_prompt", due_at=due, grace_minutes=90)
    assert tight == due + timedelta(minutes=10)
    assert loose == due + timedelta(minutes=90)


def test_a_medication_prompt_never_outlives_the_next_dose():
    """🔒 เพดานแข็ง — คำเตือนรอบเช้าที่ยังอยู่ตอนรอบเที่ยงคือคำเชิญให้**กินซ้ำ**"""
    due = datetime(2026, 9, 28, 8, 0, tzinfo=ZoneInfo("UTC"))
    next_dose = due + timedelta(minutes=20)
    deadline = expiry.deadline_for(
        "medication_prompt", due_at=due, grace_minutes=120, next_due_at=next_dose
    )
    assert deadline == next_dose, "grace ที่กว้างกว่าช่วงยาต้องถูกตัดด้วยรอบถัดไป"


def test_an_orientation_brief_dies_with_the_patients_own_day():
    """🔒 สรุปของวันนี้ที่อ่านพรุ่งนี้ไม่ใช่ข้อมูลเก่า มันคือข้อมูลผิด — และวันของใคร สำคัญ"""
    at = datetime(2026, 9, 28, 19, 0, tzinfo=ZoneInfo("UTC"))      # 02:00 ของวันที่ 29 ที่ไทย
    bangkok = expiry.deadline_for("orientation", at=at, timezone="Asia/Bangkok")
    london = expiry.deadline_for("orientation", at=at, timezone="Europe/London")
    # ที่ไทยเป็นตี 2 ของวันที่ 29 แล้ว วันของผู้ป่วยจึงเพิ่งเริ่ม · ที่ลอนดอนยังเป็นค่ำวันที่ 28
    assert bangkok == datetime(2026, 9, 29, 17, 0, tzinfo=ZoneInfo("UTC")), "เที่ยงคืนของไทย"
    assert london == datetime(2026, 9, 28, 23, 0, tzinfo=ZoneInfo("UTC")), "เที่ยงคืนของลอนดอน"
    assert bangkok != london, "วันจบตาม timezone ของผู้ป่วย ไม่ใช่ของเซิร์ฟเวอร์"


# ── C) pause / resume — เส้นความสดที่ไม่เท่ากันโดยเจตนา ──────────────────────


def test_resume_is_strictly_fresher_than_pause_for_the_same_trigger():
    """🔒 ADR-0015 ข้อ 4 — เปิดต่อคือการปลุกคน ไม่ใช่การยกเลิกการหยุด"""
    at = datetime(2026, 9, 28, 8, 0, tzinfo=ZoneInfo("UTC"))
    pause_at, pause_class = expiry.for_device_action("pause", "caregiver_request", at=at)
    resume_at, resume_class = expiry.for_device_action("resume", "caregiver_request", at=at)

    assert resume_at < pause_at
    assert resume_class == "device_resume"
    assert expiry.CLASSES[resume_class].ceiling_minutes <= expiry.CLASSES[pause_class].minutes


def test_the_same_action_expires_differently_depending_on_who_asked():
    """ชนิดมาจากที่มาของคำสั่ง ไม่ใช่จากตัวคำสั่งอย่างเดียว"""
    at = datetime(2026, 9, 28, 8, 0, tzinfo=ZoneInfo("UTC"))
    assert expiry.for_device_action("pause", "safety_signal", at=at)[1] == "safety_action"
    assert expiry.for_device_action("pause", "caregiver_request", at=at)[1] == (
        "caregiver_request_action"
    )
    assert expiry.for_device_action("pause", "reminder_due", at=at)[1] == "device_pause"


def test_an_action_with_no_rule_is_refused_rather_than_sent_without_a_deadline():
    with pytest.raises(expiry.UnknownExpiryClass):
        expiry.for_device_action("pause", "because_i_said_so")


async def test_a_device_action_carries_its_expiry_and_declares_the_class_in_audit(session, tenant):
    patient, _ = await setup_patient(session, tenant)
    with FakeClock("2026-09-28T01:00:00+00:00"):
        result = await endpoint.pause_media(
            session, scope_for(tenant), patient.patient_id, trigger="caregiver_request"
        )
    assert result["expiry_class"] == "caregiver_request_action"
    assert result["expires_at"] is not None
    events = await audit_rows(session, tenant)
    assert any(e.attributes.get("expiry_class") == "caregiver_request_action" for e in events)


async def audit_rows(session, tenant):
    from tests.conftest import audit_events

    return await audit_events(session, tenant)


# ── D) เส้นจริง — โดเมนตั้งกำหนดตายก่อนของออกไป ──────────────────────────────


async def _patient_with_doses(session, tenant, *, times, grace=30, channel="tv"):
    patient, _ = await setup_patient(session, tenant)
    patient.channels = [channel]
    for hhmm in times:
        await routines.add_routine(
            session,
            scope_for(tenant),
            patient_id=patient.patient_id,
            kind="medication",
            label="ยาเช้า",
            scheduled_time=hhmm,
            grace_minutes=grace,
        )
    await session.flush()
    return patient


async def test_a_real_medication_reminder_leaves_the_domain_with_a_deadline(session, tenant):
    """เส้นจริงทั้งเส้น — ตั้งกิจวัตร ปล่อยงานถึงกำหนด แล้วดูว่าแถวที่ส่งออกมีกำหนดตาย"""
    queue = InMemoryQueue()
    sender.install(queue)
    with FakeClock("2026-09-28T00:30:00+00:00") as clock:
        patient = await _patient_with_doses(session, tenant, times=["08:00"], grace=45)
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        clock.set("2026-09-28T01:00:00+00:00")          # 08:00 ตามเวลาไทย
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

    rows = await notifications(session, tenant, patient.patient_id)
    sent = [n for n in rows if n.channel == "tv"]
    assert sent, "ต้องมีของออกไปทาง tv"
    row = sent[0]
    assert row.expiry_class == "medication_prompt"
    assert row.expires_at is not None
    job = await jobs.get_job(session, scope_for(tenant), row.care_job_id)
    assert row.expires_at == job.due_at + timedelta(minutes=45), "ต้องเท่ากับ grace ที่ตั้งไว้"

    envelope = queue.drain()[0]
    assert envelope.expires_at == row.expires_at.timestamp(), "adapter ได้ค่าที่โดเมนตั้ง"
    assert envelope.expiry_class == "medication_prompt"


async def test_a_caregiver_notification_is_declared_never_expiring(session, tenant):
    """🔒 เส้นขอความช่วยเหลือไม่มีกำหนดตาย และนั่นเป็นการประกาศ ไม่ใช่ช่องที่ลืมเติม"""
    patient, _ = await setup_patient(session, tenant)
    with FakeClock("2026-09-28T01:00:00+00:00"):
        sent = await jobs.send_to_caregivers(
            session,
            system_scope(tenant),
            patient_id=patient.patient_id,
            text="คุณยายยังไม่ได้กินยาเช้า",
            capability="caregiver.notify",
            severity="high",
        )
    assert sent, "ต้องมีการแจ้งออกไป"
    assert sent[0].expires_at is None
    assert sent[0].expiry_class == "caregiver_help"


async def test_line_still_works_and_ignores_the_new_columns(session, tenant):
    """D) เข้ากันได้ย้อนหลัง — ช่องทางที่ไม่ใช่ TV ไม่สนใจกำหนดตาย แต่ต้องยังส่งได้"""
    with FakeClock("2026-09-28T00:30:00+00:00") as clock:
        patient = await _patient_with_doses(session, tenant, times=["08:00"], channel="line")
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()
        clock.set("2026-09-28T01:00:00+00:00")
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

    rows = [
        n for n in await notifications(session, tenant, patient.patient_id) if n.channel == "line"
    ]
    assert rows, "LINE ต้องยังส่งได้เหมือนเดิม"
    assert rows[0].expiry_class == "medication_prompt", "โดเมนตั้งให้ทุกช่องทาง"
    assert rows[0].delivery_status in ("sent", "stored", "failed")


# ── E) ฝั่งอุปกรณ์ — ทิ้งของที่หมดอายุ และนับให้เห็นแยกตามชนิด ───────────────


async def test_an_envelope_that_expired_before_the_poll_is_dropped_by_class():
    queue = InMemoryQueue()
    loop = runtime.AdapterRuntime(PollingTransport(queue, interval=0.01), clock=lambda: 2_000.0)
    queue.put(
        Envelope(
            kind="device_action",
            payload={"action": "pause"},
            expires_at=1_000.0,
            expiry_class="device_pause",
        )
    )
    stats = await loop.run(max_polls=1)

    assert loop.controller.calls == []
    assert stats.expired_by_class == {"device_pause": 1}
    assert set(stats.expired_by_class) <= set(expiry.CLASSES) | {"undeclared"}, "ตัวนับต้องไม่มี PII"


async def test_an_envelope_that_expires_while_the_link_is_down_is_not_run_on_recovery():
    """🔒 เน็ตกลับมาแล้วไม่ใช่เหตุผลให้ทำของที่เหตุผลหมดอายุไปแล้ว"""
    clock = {"t": 1_000.0}
    queue = InMemoryQueue()
    queue.put(
        Envelope(
            kind="device_action",
            payload={"action": "pause"},
            expires_at=1_100.0,
            expiry_class="device_pause",
        )
    )

    class FlakyLink(PollingTransport):
        def __init__(self, q):
            super().__init__(q, interval=0.001)
            self.tries = 0

        async def next_batch(self):
            self.tries += 1
            if self.tries <= 2:
                clock["t"] += 100.0          # เวลาเดินระหว่างที่ต่อไม่ได้
                raise ConnectionError("เน็ตหลุด")
            return await super().next_batch()

    loop = runtime.AdapterRuntime(
        FlakyLink(queue), clock=lambda: clock["t"], backoff_base=0.001, backoff_cap=0.002
    )
    stats = await loop.run(max_polls=1)

    assert stats.reconnects == 2
    assert loop.controller.calls == [], "หมดอายุระหว่างเน็ตหลุด ต้องไม่ถูกทำตอนกลับมา"
    assert stats.expired_by_class == {"device_pause": 1}


async def test_a_stale_envelope_delivered_twice_is_counted_once_and_never_run():
    queue = InMemoryQueue()
    loop = runtime.AdapterRuntime(PollingTransport(queue, interval=0.01), clock=lambda: 2_000.0)
    stale = Envelope(
        kind="device_action",
        payload={"action": "pause"},
        expires_at=1_000.0,
        expiry_class="device_pause",
        envelope_id="stale-1",
    )
    queue.put(stale)
    await loop.run(max_polls=1)
    queue.put(stale)
    stats = await loop.run(max_polls=2)

    assert loop.controller.calls == []
    assert stats.expired == 1 and stats.duplicates == 1, "ซ้ำต้องถูกตัดก่อน ไม่นับหมดอายุสองรอบ"


async def test_a_superseded_reminder_does_not_appear_twice_on_the_screen():
    """🔒 เตือนครั้งที่สองของงานเดียวกันคือ **ใบแทน** ไม่ใช่ใบเพิ่ม

    ถ้าปล่อยทั้งสองใบ ผู้ป่วยเห็นคำเตือนเรื่องเดียวกันสองอันและไม่รู้ว่าต้องตอบอันไหน
    """
    queue, loop = runtime.build(interval=0.01)
    plan = {"speak": True, "needs_answer": True}
    queue.put(
        Envelope(
            kind="present",
            payload={"text": "ยาเช้า (ครั้งที่ 1)", "plan": plan, "care_job_id": "job-1"},
            stream="job:job-1",
            revision=11,
        )
    )
    queue.put(
        Envelope(
            kind="present",
            payload={"text": "ยาเช้า (ครั้งที่ 2)", "plan": plan, "care_job_id": "job-1"},
            stream="job:job-1",
            revision=12,
        )
    )
    stats = await loop.run(max_polls=1)

    assert loop.speaker.spoken == ["ยาเช้า (ครั้งที่ 2)"], "ต้องเหลือใบใหม่สุดใบเดียว"
    assert stats.superseded == 1 and stats.presented == 1


async def test_device_actions_are_never_collapsed_as_supersession():
    """คำสั่งต่ออุปกรณ์แต่ละใบเป็นคำสั่งของตัวเอง — `stream = None` จึงไม่มีใครแทนได้"""
    queue, loop = runtime.build(interval=0.01)
    queue.put(Envelope(kind="device_action", payload={"action": "pause"}))
    queue.put(Envelope(kind="device_action", payload={"action": "resume"}))
    stats = await loop.run(max_polls=1)

    assert loop.controller.calls == ["pause", "resume"]
    assert stats.superseded == 0


# ── F) ปุ่มที่กดตอบคำถามที่หมดอายุ ต้องไม่กลายเป็นหลักฐาน ────────────────────


def test_a_prompt_book_treats_what_it_cannot_remember_as_still_answerable():
    """🔒 จำไม่ได้ ≠ หมดอายุ — ถ้าตีความกลับกัน ทุกครั้งที่แอปรีสตาร์ต การกดจริงจะถูกปฏิเสธ"""
    book = PromptBook()
    assert book.is_fresh("job-never-seen", at=9_999.0)
    book.remember("job-1", 1_000.0)
    assert book.is_fresh("job-1", at=999.0)
    assert not book.is_fresh("job-1", at=1_001.0)
    book.remember("job-2", None)                      # โดเมนประกาศว่าไม่มีกำหนดตาย
    assert book.is_fresh("job-2", at=9_999.0)


async def test_pressing_done_on_an_expired_prompt_is_refused_before_it_becomes_evidence(
    session, tenant
):
    patient, _ = await setup_patient(session, tenant)
    with FakeClock("2026-09-28T00:30:00+00:00") as clock:
        await routines.add_routine(
            session,
            scope_for(tenant),
            patient_id=patient.patient_id,
            kind="medication",
            label="ยาเช้า",
            scheduled_time="08:00",
        )
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()
        clock.set("2026-09-28T01:00:00+00:00")
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

        job = (await jobs.open_jobs(session, scope_for(tenant), patient.patient_id))[0]
        book = PromptBook()
        book.remember(job.care_job_id, 1_000.0)

        with pytest.raises(StalePrompt):
            await inbound.key_pressed(
                session, scope_for(tenant), job.care_job_id, "BUTTON_A",
                prompts=book, at=2_000.0,
            )
        fresh = await jobs.get_job(session, scope_for(tenant), job.care_job_id)
        assert fresh.evidence in (None, {}), "การกดที่หมดอายุต้องไม่สร้างหลักฐาน"
        assert fresh.state != "confirmed"

        # เวลาที่ยังสด กดได้ตามปกติ
        await inbound.key_pressed(
            session, scope_for(tenant), job.care_job_id, "BUTTON_A", prompts=book, at=500.0
        )
        done = await jobs.get_job(session, scope_for(tenant), job.care_job_id)
        assert done.evidence["kind"] == "patient_confirmed"


async def test_asking_for_help_is_never_blocked_by_freshness(session, tenant):
    """🔒 การกดขอความช่วยเหลือคือเหตุการณ์ของ **ตอนนี้** ไม่ใช่คำตอบของงานเมื่อเช้า

    ปฏิเสธมันเพราะ "คำถามหมดอายุ" คือการเงียบในจุดที่เงียบไม่ได้
    """
    patient, _ = await setup_patient(session, tenant)
    with FakeClock("2026-09-28T01:00:00+00:00"):
        await routines.add_routine(
            session,
            scope_for(tenant),
            patient_id=patient.patient_id,
            kind="medication",
            label="ยาเช้า",
            scheduled_time="08:00",
        )
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

        job = (await jobs.open_jobs(session, scope_for(tenant), patient.patient_id))[0]
        book = PromptBook()
        book.remember(job.care_job_id, 1_000.0)
        intent = await inbound.key_pressed(
            session, scope_for(tenant), job.care_job_id, "BUTTON_Y", prompts=book, at=9_999.0
        )
    assert intent == "help"


async def test_the_runtime_remembers_the_deadline_of_prompts_that_need_an_answer():
    queue = InMemoryQueue()
    loop = runtime.AdapterRuntime(PollingTransport(queue, interval=0.01), clock=lambda: 500.0)
    queue.put(
        Envelope(
            kind="present",
            payload={
                "text": "ยาเช้า",
                "plan": {"speak": False, "needs_answer": True},
                "care_job_id": "job-9",
            },
            expires_at=1_000.0,
        )
    )
    queue.put(
        Envelope(
            kind="present",
            payload={"text": "สวัสดีตอนเช้า", "plan": {"speak": False}, "care_job_id": "job-8"},
        )
    )
    await loop.run(max_polls=1)

    assert not loop.prompts.is_fresh("job-9", at=2_000.0)
    assert len(loop.prompts) == 1, "ข้อความที่ไม่ต้องการคำตอบไม่ต้องจำ"


# ── G) ขอบของ grace_minutes (ADR-0018) และเครื่องวัดเพดาน resume (ADR-0019) ──


async def test_a_grace_that_expires_before_a_person_can_react_is_refused(session, tenant):
    """🔒 คำเตือนที่หายก่อนคนทันขยับ เท่ากับไม่เคยเตือน — ต้องพังตอนตั้ง"""
    from care_addons.care_routine import services as routine_svc

    patient, _ = await setup_patient(session, tenant)
    with pytest.raises(routine_svc.GraceOutOfRange):
        await routines.add_routine(
            session, scope_for(tenant), patient_id=patient.patient_id,
            kind="medication", label="ยาเช้า", scheduled_time="08:00", grace_minutes=1,
        )
    await session.rollback()


async def test_a_grace_longer_than_a_day_is_refused(session, tenant):
    from care_addons.care_routine import services as routine_svc

    patient, _ = await setup_patient(session, tenant)
    with pytest.raises(routine_svc.GraceOutOfRange):
        await routines.add_routine(
            session, scope_for(tenant), patient_id=patient.patient_id,
            kind="activity", label="เดินเล่น", scheduled_time="17:00", grace_minutes=2000,
        )
    await session.rollback()


async def test_an_unusually_wide_grace_is_allowed_but_never_silent(session, tenant):
    """🔒 พื้นที่ตรงกลางเป็นของทีมดูแล — เราไม่ห้าม แต่ต้องไม่ผ่านเงียบ ๆ"""

    patient, _ = await setup_patient(session, tenant)
    item = await routines.add_routine(
        session, scope_for(tenant), patient_id=patient.patient_id,
        kind="activity", label="เดินเล่น", scheduled_time="17:00", grace_minutes=600,
    )
    assert item.grace_warning and "ชั่วโมง" in item.grace_warning
    events = await audit_rows(session, tenant)
    assert any(e.attributes.get("grace_flag") == "wide" for e in events)

    normal = await routines.add_routine(
        session, scope_for(tenant), patient_id=patient.patient_id,
        kind="activity", label="อาบน้ำ", scheduled_time="18:00", grace_minutes=30,
    )
    assert normal.grace_warning is None


def test_resume_can_never_be_looser_than_pause_for_any_trigger():
    """🔒 ข้อห้ามจากใบงาน — ห้ามลดความเข้มของ resume ให้ต่ำกว่า pause ไม่ว่าทางไหน"""
    at = datetime(2026, 9, 28, 8, 0, tzinfo=ZoneInfo("UTC"))
    for trigger in expiry.ACTION_CLASS_BY_TRIGGER:
        resume_at, _ = expiry.for_device_action("resume", trigger, at=at)
        pause_at, _ = expiry.for_device_action("pause", trigger, at=at, )
        if trigger == "reminder_due":
            continue          # pause ผูกกับช่วงของงาน ไม่ใช่เวลาคงที่ — เทียบตรง ๆ ไม่ได้
        assert resume_at <= pause_at, f"trigger {trigger}: resume หลวมกว่า pause"


async def test_headroom_is_measured_in_coarse_buckets_with_nothing_about_the_person():
    """ADR-0019 — หลักฐานสำหรับทบทวนเพดาน 1 นาทีของ resume โดยไม่แตะพฤติกรรมผู้ป่วย"""
    queue = InMemoryQueue()
    loop = runtime.AdapterRuntime(PollingTransport(queue, interval=0.01), clock=lambda: 1_000.0)
    queue.put(
        Envelope(
            kind="device_action", payload={"action": "resume"},
            expires_at=1_000.5, expiry_class="device_resume",
        )
    )
    queue.put(
        Envelope(
            kind="device_action", payload={"action": "pause"},
            expires_at=1_120.0, expiry_class="device_pause",
        )
    )
    await loop.run(max_polls=1)

    assert loop.stats.headroom_buckets == {
        "device_resume": {"lt_1s": 1},
        "device_pause": {"ge_30s": 1},
    }
    assert loop.controller.calls == ["resume", "pause"], "ยังไม่หมดอายุ ต้องยังทำ"
