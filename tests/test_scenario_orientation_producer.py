"""ผู้ผลิตสรุปประจำวัน — ปิดช่องที่ ADR-0016 เขียนไว้เองว่า "กฎพร้อมแต่ยังไม่มีผู้ผลิต"

ตอบ task-6bb0d2bd Phase B · ข้อมูลสมมติล้วน ไม่มีผู้ป่วยจริง
"""

from __future__ import annotations

from datetime import date

from core.clock import FakeClock

from adapters.care_tv import runtime, sender
from adapters.care_tv.transport import InMemoryQueue, PollingTransport
from care_addons.care_escalation import services as jobs
from care_addons.care_orientation import producer
from tests.conftest import notifications, scope_for, setup_patient


async def _patient(session, tenant, *, timezone="Asia/Bangkok", quiet_hours=None, channel="tv"):
    patient, _ = await setup_patient(
        session, tenant, timezone=timezone, quiet_hours=quiet_hours
    )
    patient.channels = [channel]
    await session.flush()
    return patient


# ── 1) ส่งจริง และกำหนดตายเป็นสิ้นวันของผู้ป่วยเอง ──────────────────────────


async def test_the_brief_goes_out_with_a_deadline_at_the_end_of_the_patients_own_day(
    session, tenant
):
    queue = InMemoryQueue()
    sender.install(queue)
    with FakeClock("2026-09-28T02:00:00+00:00"):          # 09:00 ที่ไทย
        patient = await _patient(session, tenant)
        row = await producer.publish_daily_brief(session, scope_for(tenant), patient.patient_id)

    assert row is not None and row.channel == "tv"
    assert row.expiry_class == "orientation"
    # เที่ยงคืนของวันที่ 29 ตามเวลาไทย = 17:00Z ของวันที่ 28
    assert row.expires_at.isoformat() == "2026-09-28T17:00:00+00:00"
    assert row.care_job_id is None, "สรุปประจำวันไม่ใช่งานที่ต้องตอบ"

    envelope = queue.drain()[0]
    assert envelope.expiry_class == "orientation"
    assert envelope.stream == producer.stream_for(patient.patient_id, date(2026, 9, 28))


async def test_two_patients_in_different_timezones_get_different_deadlines(session, tenant):
    with FakeClock("2026-09-28T02:00:00+00:00"):
        bangkok = await _patient(session, tenant)
        london = await _patient(session, tenant, timezone="Europe/London", channel="app")
        a = await producer.publish_daily_brief(session, scope_for(tenant), bangkok.patient_id)
        b = await producer.publish_daily_brief(session, scope_for(tenant), london.patient_id)

    assert a.expires_at != b.expires_at, "วันของใคร จบตอนนั้น"
    assert a.expires_at.isoformat() == "2026-09-28T17:00:00+00:00"   # เที่ยงคืนไทย
    assert b.expires_at.isoformat() == "2026-09-28T23:00:00+00:00"   # เที่ยงคืนลอนดอน


# ── 2) เรียกซ้ำ · ข้ามวัน · การแทนที่ ────────────────────────────────────────


async def test_publishing_the_same_brief_twice_in_one_day_sends_nothing_the_second_time(
    session, tenant
):
    """🔒 ข้อความเดิมของวันเดิม = ไม่มีอะไรใหม่ · ส่งซ้ำคือรบกวนโดยไม่มีข้อมูลเพิ่ม"""
    with FakeClock("2026-09-28T02:00:00+00:00"):
        patient = await _patient(session, tenant)
        first = await producer.publish_daily_brief(session, scope_for(tenant), patient.patient_id)
        again = await producer.publish_daily_brief(session, scope_for(tenant), patient.patient_id)

    assert first is not None
    assert again is None, "ไม่มีอะไรใหม่ ต้องไม่ส่ง — และต่างจากส่งไม่สำเร็จ"
    rows = await notifications(session, tenant, patient.patient_id)
    assert len([r for r in rows if r.stream == first.stream]) == 1


async def test_a_changed_brief_on_the_same_day_replaces_the_earlier_one(session, tenant):
    """ใบใหม่ในสายเดียวกัน = ใบแทน · ฝั่งอุปกรณ์ต้องเหลือใบเดียว"""
    queue = InMemoryQueue()
    sender.install(queue)
    with FakeClock("2026-09-28T02:00:00+00:00") as clock:
        patient = await _patient(session, tenant)
        first = await producer.publish_daily_brief(session, scope_for(tenant), patient.patient_id)

        clock.set("2026-09-28T05:00:00+00:00")     # 12:00 ที่ไทย — เวลาในข้อความเปลี่ยน
        second = await producer.publish_daily_brief(session, scope_for(tenant), patient.patient_id)

    assert second is not None and second.stream == first.stream
    assert second.id > first.id

    loop = runtime.AdapterRuntime(PollingTransport(queue, interval=0.01), clock=lambda: 0.0)
    stats = await loop.run(max_polls=1)
    assert stats.presented == 1 and stats.superseded == 1, "เหลือใบเดียวบนจอ"


async def test_a_new_day_is_a_new_stream_and_does_not_replace_yesterday(session, tenant):
    """🔒 ถ้าสายงานไม่มีวันที่ สรุปของเมื่อวานจะถูกนับเป็นใบเดียวกับของวันนี้"""
    with FakeClock("2026-09-28T02:00:00+00:00") as clock:
        patient = await _patient(session, tenant)
        first = await producer.publish_daily_brief(session, scope_for(tenant), patient.patient_id)
        clock.set("2026-09-29T02:00:00+00:00")
        second = await producer.publish_daily_brief(session, scope_for(tenant), patient.patient_id)

    assert first.stream != second.stream
    assert second is not None, "วันใหม่ต้องได้สรุปใหม่เสมอ แม้ข้อความจะบังเอิญเหมือนกัน"


# ── 3) quiet hours · หลักฐาน · การทิ้งของข้ามวัน ─────────────────────────────


async def test_the_brief_is_downgraded_in_quiet_hours_without_the_producer_knowing(
    session, tenant
):
    """ผู้ผลิตขอ overlay + เสียง · `effective_presentation()` เป็นผู้ตัดสิน (ADR-0014 ข้อ 2)"""
    with FakeClock("2026-09-27T18:00:00+00:00"):          # 01:00 ที่ไทย
        patient = await _patient(session, tenant, quiet_hours=("21:00", "07:00"))
        row = await producer.publish_daily_brief(session, scope_for(tenant), patient.patient_id)

    assert producer.REQUESTED_PRESENTATION["surface"] == "overlay"
    assert row.presentation["surface"] == "ambient", "ไม่ยึดจอในเวลาที่เขาควรได้พัก"
    assert row.presentation["speak"] is False


async def test_the_brief_can_never_become_evidence_of_anything(session, tenant):
    """🔒 ไม่มีงาน ไม่มีปุ่ม ไม่มีอะไรให้กลายเป็นหลักฐาน (ADR-0014 ข้อ 5)"""
    with FakeClock("2026-09-28T02:00:00+00:00"):
        patient = await _patient(session, tenant)
        row = await producer.publish_daily_brief(session, scope_for(tenant), patient.patient_id)

        assert row.care_job_id is None
        assert producer.REQUESTED_PRESENTATION["response"] == "none"
        assert await jobs.open_jobs(session, scope_for(tenant), patient.patient_id) == []

        await jobs.mark_presented(session, scope_for(tenant), row.id)
        assert row.presented_at is not None
        assert await jobs.open_jobs(session, scope_for(tenant), patient.patient_id) == []


async def test_yesterdays_brief_is_dropped_when_the_device_reconnects_the_next_morning(
    session, tenant
):
    """🔒 เครื่องปิดข้ามคืนแล้วเปิดมา — สรุปของเมื่อวานไม่ใช่ข้อมูลเก่า มันคือข้อมูลผิด"""
    queue = InMemoryQueue()
    sender.install(queue)
    with FakeClock("2026-09-28T02:00:00+00:00"):
        patient = await _patient(session, tenant)
        row = await producer.publish_daily_brief(session, scope_for(tenant), patient.patient_id)

    # เครื่องกลับมาออนไลน์ 09:00 ของวันรุ่งขึ้นตามเวลาไทย
    next_morning = row.expires_at.timestamp() + 16 * 3600
    loop = runtime.AdapterRuntime(
        PollingTransport(queue, interval=0.01), clock=lambda: next_morning
    )
    stats = await loop.run(max_polls=1)

    assert stats.presented == 0
    assert stats.expired_by_class == {"orientation": 1}


def test_the_capability_that_sends_belongs_to_the_thing_that_sends():
    """🔒 `DECLARED` เก็บได้ฟังก์ชันเดียวต่อหนึ่ง capability — ชนกันแล้ว `/policy` รายงานผิด"""
    from care_addons.ap_policy.services import DECLARED
    from care_addons.care_orientation import services as orientation

    assert orientation  # ให้ decorator ของทั้งสองไฟล์ทำงานแน่นอน
    assert DECLARED["orientation.brief.send"]["function"].endswith(
        "producer.publish_daily_brief"
    )
