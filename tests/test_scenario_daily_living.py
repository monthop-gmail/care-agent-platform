"""Scenario S6, S10, S14, S15 — Daily Living & Safety (M5)

    S6  เข้าเครื่องซักผ้าแล้วผ้าค้างในเครื่อง → ขั้นตอนค้าง → เตือน → ผู้ดูแล
    S10 ซื้ออาหารซ้ำทั้งที่ของยังไม่หมดอายุ  → เตือนว่ามีอยู่แล้ว (ไม่ห้ามซื้อ)
    S14 "ชุดนี้ใส่แล้วหรือยัง" — จำไม่ได้    → workflow ที่ปลอดภัย ไม่ใช่การเดา
    S15 wearable แจ้งว่าอาจล้ม               → ปลุกทุกคน · แต่สัญญาณที่ไม่มั่นใจไม่ปลุกใคร
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from care_addons.ap_tenancy.clock import FakeClock
from care_addons.ap_tenancy.services import Principal
from care_addons.care_activity import services as activities
from care_addons.care_home import services as home
from care_addons.care_inventory import services as inventory
from care_addons.care_safety import services as safety
from tests.conftest import notifications, scope_for, setup_patient, system_scope

HUMAN = Principal(type="human", id="user-1", display_name="ลูกสาว")
AGENT = Principal(type="agent", id="care-agent")
TODAY = date(2026, 8, 19)

FULL_PROFILE = {
    "routine": True,
    "medication": True,
    "caregiver_escalation": True,
    "safety": True,
}


# ── S6: งานหลายขั้นตอน ────────────────────────────────────────────────────────

async def test_s6_machine_finished_is_not_task_finished(session, tenant):
    """🔒 activity_rules ข้อ 1 — ผ้าที่ซักเสร็จแต่ยังอยู่ในเครื่องคือปัญหา ไม่ใช่ความสำเร็จ"""
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        activity = await activities.start_activity(
            session, scope, patient_id=patient.patient_id, activity_type="laundry", label="ซักผ้า"
        )
        await session.commit()

        steps = await activities.steps_of(session, scope, activity.activity_id)
        assert [s.state for s in steps] == ["in_progress", "not_started", "not_started", "not_started"]
        assert steps[0].care_job_id is not None      # ขั้นแรกเป็นงานที่เตือนได้จริง

        # ผู้ป่วยกดเริ่มเครื่องแล้ว
        clock.advance(minutes=5)
        await activities.complete_step(session, scope, steps[0].step_id)
        await session.commit()
        steps = await activities.steps_of(session, scope, activity.activity_id)
        # ขั้นที่รอเครื่อง — ไม่เตือนผู้ป่วยตอนนี้เพราะเขาทำอะไรไม่ได้
        assert steps[1].state == "waiting"
        assert steps[1].care_job_id is None

        # เครื่องแจ้งว่าเสร็จ
        clock.advance(minutes=45)
        await activities.external_signal(
            session, scope, activity_id=activity.activity_id,
            event="washing_machine.finished", source_system="smart-home-hub",
        )
        await session.commit()

        activity_now = await activities.get_activity(session, scope, activity.activity_id)
        assert activity_now.state != "completed"     # 🔒 เครื่องเสร็จ ≠ งานเสร็จ
        steps = await activities.steps_of(session, scope, activity.activity_id)
        assert steps[1].state == "completed"
        assert steps[2].state == "in_progress"       # ถึงคิวคนแล้ว: เอาผ้าออก
        assert steps[2].care_job_id is not None


async def test_s6_stalled_step_reaches_the_caregiver(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, caregiver = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        activity = await activities.start_activity(
            session, scope, patient_id=patient.patient_id, activity_type="laundry"
        )
        await session.commit()
        steps = await activities.steps_of(session, scope, activity.activity_id)

        # ยังไม่ถึงเวลาที่ถือว่าค้าง
        clock.advance(minutes=20)
        assert await activities.sweep_stalled(session, system_scope(tenant)) == 0

        clock.advance(minutes=20)      # รวม 40 นาที > stalled_after_minutes 30 ของขั้นแรก
        assert await activities.sweep_stalled(session, system_scope(tenant)) == 1
        await session.commit()

        steps = await activities.steps_of(session, scope, activity.activity_id)
        assert steps[0].state == "needs_help"
        sent = await notifications(session, tenant, patient.patient_id, audience="caregiver")
        assert any("ค้างมา" in n.text for n in sent)
        assert sent[0].target_principal_id == caregiver.principal_id

        # รายงานซ้ำรอบถัดไปไม่เกิดขึ้น — กัน notification storm
        clock.advance(minutes=30)
        assert await activities.sweep_stalled(session, system_scope(tenant)) == 0


async def test_activity_without_a_known_workflow_needs_explicit_steps(session, tenant):
    """🔒 ระบบไม่คิดขั้นตอนเองสำหรับงานที่ไม่มี workflow ตั้งต้น"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        with pytest.raises(ValueError, match="ส่ง steps มาด้วย"):
            await activities.start_activity(
                session, scope, patient_id=patient.patient_id, activity_type="bathing"
            )
        await session.rollback()


# ── S10: ของที่บ้าน ───────────────────────────────────────────────────────────

async def test_s10_tells_you_it_is_already_at_home_without_forbidding(session, tenant):
    """🔒 inventory_rules ข้อ 2 — เตือนว่ามีอยู่แล้วได้ ห้ามห้ามซื้อ"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        await inventory.add_item(
            session, scope, patient_id=patient.patient_id, name="นมกล่อง",
            category="drink", quantity=6, unit="กล่อง", location="ตู้เย็นชั้นบน",
            expires_on=TODAY + timedelta(days=5),
        )
        await session.commit()

        answer = await inventory.check_before_buying(
            session, scope, patient.patient_id, name="นมกล่อง", today=TODAY
        )
        await session.commit()

        assert len(answer["already_at_home"]) == 1
        assert answer["already_at_home"][0]["location"] == "ตู้เย็นชั้นบน"
        assert "มี 'นมกล่อง' อยู่แล้ว" in answer["message"]
        assert "จะซื้อเพิ่มก็ได้" in answer["message"]
        # 🔒 ไม่มีคำตอบไหนที่แปลว่า "ห้ามซื้อ"
        assert not any(k in answer for k in ("blocked", "forbidden", "allowed", "should_buy"))


async def test_unknown_expiry_is_reported_as_unknown_not_guessed(session, tenant):
    """🔒 inventory_rules ข้อ 1 — ไม่รู้วันหมดอายุ ต้องตอบว่าไม่รู้"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        await inventory.add_item(
            session, scope, patient_id=patient.patient_id, name="ข้าวสาร",
            category="food", location="ใต้อ่าง",
        )
        await session.commit()

        answer = await inventory.check_before_buying(
            session, scope, patient.patient_id, name="ข้าวสาร", today=TODAY
        )
        assert answer["already_at_home"][0]["expires_on"] is None
        assert answer["already_at_home"][0]["expiry_known"] is False
        assert "ยังไม่ได้บันทึกวันหมดอายุ" in answer["message"]

        report = await inventory.expiring_soon(session, scope, patient.patient_id, today=TODAY)
        # ของที่ไม่รู้วันหมดอายุต้องเห็นได้ ไม่ใช่หายไปในกอง "ไม่มีปัญหา"
        assert [i["name"] for i in report["expiry_unknown"]] == ["ข้าวสาร"]


async def test_expired_items_are_facts_from_the_date(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        for name, day in (
            ("โยเกิร์ต", TODAY - timedelta(days=1)),
            ("ขนมปัง", TODAY + timedelta(days=2)),
            ("ไข่ไก่", TODAY + timedelta(days=30)),
        ):
            await inventory.add_item(
                session, scope, patient_id=patient.patient_id, name=name,
                category="food", expires_on=day,
            )
        await session.commit()

        report = await inventory.expiring_soon(
            session, scope, patient.patient_id, within_days=3, today=TODAY
        )
        assert [i["name"] for i in report["expired"]] == ["โยเกิร์ต"]
        assert [i["name"] for i in report["expiring_soon"]] == ["ขนมปัง"]

        answer = await inventory.check_before_buying(
            session, scope, patient.patient_id, name="โยเกิร์ต", today=TODAY
        )
        assert answer["already_at_home"] == []          # ของหมดอายุไม่นับว่ามีใช้ได้
        assert len(answer["expired_at_home"]) == 1


# ── S14: ของใช้ประจำตัว ───────────────────────────────────────────────────────

async def test_s14_i_dont_remember_leads_to_a_safe_workflow(session, tenant):
    """🔒 home_rules ข้อ 2 — ไม่แน่ใจ = unknown แล้วเสนอทางที่ปลอดภัย ห้ามบอกว่าสะอาด"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        shirt = await home.add_item(
            session, scope, patient_id=patient.patient_id, kind="clothing",
            label="เสื้อเชิ้ตลายฟ้า", home_location="ตู้เสื้อผ้าชั้นบน", state="ready",
        )
        await session.commit()

        suggestion = await home.mark_unsure(session, scope, shirt.item_id)
        await session.commit()

        assert suggestion["suggested_state"] == "in_laundry"
        assert "ตะกร้าผ้าที่ใช้แล้ว" in suggestion["message"]
        assert "สะอาด" not in suggestion["message"]
        await session.refresh(shirt)
        # ระบบบันทึกความไม่รู้ตามจริง และ **ไม่** เปลี่ยนสถานะให้เอง
        assert shirt.state == "unknown"


async def test_agent_cannot_decide_that_a_shirt_is_clean(session, tenant):
    """🔒 home_rules ข้อ 1 — เปลี่ยนสถานะได้จากการยืนยันของคนเท่านั้น"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        shirt = await home.add_item(
            session, scope, patient_id=patient.patient_id, kind="clothing", label="เสื้อสีขาว",
        )
        await session.commit()
        item_id = shirt.item_id      # เก็บไว้ก่อน — หลัง rollback object จะ expire

        with pytest.raises(home.HomeRuleViolation, match="คนเท่านั้น"):
            await home.set_state(session, scope, item_id, state="ready", confirmed_by=AGENT)
        await session.rollback()

        confirmed = await home.set_state(
            session, scope, item_id, state="ready", confirmed_by=HUMAN
        )
        await session.commit()
        assert confirmed.state == "ready"
        assert confirmed.last_confirmed_by["id"] == "user-1"


async def test_where_is_answers_from_records_or_says_it_does_not_know(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        await home.add_item(
            session, scope, patient_id=patient.patient_id, kind="keys",
            label="กุญแจบ้าน", home_location="ตะกร้าข้างประตู",
        )
        await session.commit()

        found = await home.where_is(session, scope, patient.patient_id, label="กุญแจ")
        assert found["found"] is True
        assert "ตะกร้าข้างประตู" in found["message"]

        missing = await home.where_is(session, scope, patient.patient_id, label="แว่นตา")
        assert missing["found"] is False
        assert "ไม่ทราบว่าอยู่ไหน" in missing["message"]


async def test_setting_clothes_aside_for_tomorrow(session, tenant):
    with FakeClock("2026-08-19T13:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)
        scope = scope_for(tenant)
        shirt = await home.add_item(
            session, scope, patient_id=patient.patient_id, kind="clothing",
            label="ชุดสุภาพสำหรับไปหาหมอ", state="ready",
        )
        tomorrow = TODAY + timedelta(days=1)
        await home.set_aside(
            session, scope, [shirt.item_id], for_date=tomorrow, reason="นัดหมอ 09:00",
        )
        await session.commit()

        prepared = await home.prepared_for(session, scope, patient.patient_id, tomorrow)
        assert [i.label for i in prepared] == ["ชุดสุภาพสำหรับไปหาหมอ"]
        assert prepared[0].set_aside_reason == "นัดหมอ 09:00"


# ── S15: สัญญาณความปลอดภัย ────────────────────────────────────────────────────

async def test_s15_high_confidence_fall_signal_wakes_everyone(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, caregiver = await setup_patient(session, tenant, profile=FULL_PROFILE)
        scope = scope_for(tenant)
        event = await safety.report_signal(
            session,
            scope,
            patient_id=patient.patient_id,
            kind="fall_suspected",
            source={"kind": "wearable", "system": "watch-vendor", "device_id": "w-001"},
            confidence=0.93,
        )
        await session.commit()

        assert event.severity == "critical"
        assert event.escalated is True
        sent = await notifications(session, tenant, patient.patient_id, audience="caregiver")
        assert len(sent) == 1
        assert sent[0].target_principal_id == caregiver.principal_id
        # 🔒 ข้อความพูดถึงสัญญาณของอุปกรณ์ ไม่ใช่สภาพของผู้ป่วย
        assert "อุปกรณ์รายงาน" in sent[0].text
        for banned in ("ผู้ป่วยล้ม", "บาดเจ็บ", "อาการ"):
            assert banned not in sent[0].text


async def test_s15_low_confidence_signal_is_recorded_but_wakes_nobody(session, tenant):
    """🔒 safety_rules ข้อ 3 — false alert ทำให้อุปกรณ์ถูกปิด แล้วครั้งที่จริงจะไม่มีใครฟัง"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant, profile=FULL_PROFILE)
        scope = scope_for(tenant)
        event = await safety.report_signal(
            session,
            scope,
            patient_id=patient.patient_id,
            kind="fall_suspected",
            source={"kind": "wearable", "system": "watch-vendor"},
            confidence=0.35,
        )
        await session.commit()

        assert event.escalated is False
        assert await notifications(session, tenant, patient.patient_id, audience="caregiver") == []
        # แต่ยังอยู่ในระบบให้คนตามดูได้ ไม่ได้ถูกทิ้ง
        assert [e.safety_event_id for e in await safety.open_events(session, scope, patient.patient_id)] == [
            event.safety_event_id
        ]


async def test_repeated_signals_are_one_event_not_a_storm(session, tenant):
    """🔒 safety_rules ข้อ 4 — เซ็นเซอร์ประตูที่แจ้งทุก 30 วินาทีต้องไม่ปลุกคน 30 ครั้ง"""
    with FakeClock("2026-08-19T01:00:00+00:00") as clock:
        patient, _ = await setup_patient(session, tenant, profile=FULL_PROFILE)
        scope = scope_for(tenant)
        first = await safety.report_signal(
            session, scope, patient_id=patient.patient_id, kind="door_left_open",
            source={"kind": "door_sensor", "system": "smart-home-hub"},
        )
        for _ in range(4):
            clock.advance(minutes=2)
            again = await safety.report_signal(
                session, scope, patient_id=patient.patient_id, kind="door_left_open",
                source={"kind": "door_sensor", "system": "smart-home-hub"},
            )
            assert again.safety_event_id == first.safety_event_id
        await session.commit()

        await session.refresh(first)
        assert first.repeat_count == 5
        assert len(await notifications(session, tenant, patient.patient_id, audience="caregiver")) == 1

        # พ้นหน้าต่างรวมสัญญาณแล้ว = เหตุการณ์ใหม่จริง ๆ
        clock.advance(minutes=20)
        later = await safety.report_signal(
            session, scope, patient_id=patient.patient_id, kind="door_left_open",
            source={"kind": "door_sensor", "system": "smart-home-hub"},
        )
        await session.commit()
        assert later.safety_event_id != first.safety_event_id


async def test_signal_without_a_source_system_is_rejected(session, tenant):
    """🔒 event/v1 — external event ต้องรู้ตลอดไปว่ามาจากระบบไหน"""
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant, profile=FULL_PROFILE)
        scope = scope_for(tenant)
        with pytest.raises(ValueError, match="source.system"):
            await safety.report_signal(
                session, scope, patient_id=patient.patient_id, kind="no_response",
                source={"kind": "phone"},
            )
        await session.rollback()


async def test_safety_needs_the_feature_enabled_for_that_patient(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant)   # ไม่ได้เปิด safety
        scope = scope_for(tenant)
        with pytest.raises(safety.SafetyRuleViolation, match="care_profile.safety"):
            await safety.report_signal(
                session, scope, patient_id=patient.patient_id, kind="door_left_open",
                source={"kind": "door_sensor", "system": "hub"},
            )
        await session.rollback()


async def test_only_a_human_can_acknowledge_a_safety_signal(session, tenant):
    with FakeClock("2026-08-19T01:00:00+00:00"):
        patient, _ = await setup_patient(session, tenant, profile=FULL_PROFILE)
        scope = scope_for(tenant)
        event = await safety.report_signal(
            session, scope, patient_id=patient.patient_id, kind="stove_left_on",
            source={"kind": "smart_appliance", "system": "kitchen-hub"},
        )
        await session.commit()
        event_id = event.safety_event_id      # เก็บไว้ก่อน — หลัง rollback object จะ expire

        with pytest.raises(safety.SafetyRuleViolation, match="คนเท่านั้น"):
            await safety.acknowledge(session, scope, event_id, acknowledged_by=AGENT)
        await session.rollback()

        acked = await safety.acknowledge(
            session, scope, event_id, acknowledged_by=HUMAN, note="ปิดเตาให้แล้ว"
        )
        await session.commit()
        assert acked.state == "acknowledged"
        assert acked.acknowledged_by["id"] == "user-1"


async def test_daily_summary_reports_open_signals_without_claiming_safety(session, tenant):
    from care_addons.care_orchestrator import services as orchestrator

    with FakeClock("2026-08-19T13:05:00+00:00"):
        patient, _ = await setup_patient(session, tenant, profile=FULL_PROFILE)
        scope = scope_for(tenant)
        await safety.report_signal(
            session, scope, patient_id=patient.patient_id, kind="door_left_open",
            source={"kind": "door_sensor", "system": "smart-home-hub"},
        )
        await session.commit()

        row = await orchestrator.send_daily_summary(session, system_scope(tenant), patient)
        await session.commit()
        assert len(row.facts["safety_signals"]) == 1
        assert "สัญญาณความปลอดภัยที่ยังไม่ปิด 1 รายการ" in row.text
        # 🔒 ไม่มีสัญญาณ ≠ ปลอดภัย — สรุปต้องไม่เคยพูดว่าปลอดภัย
        assert "ปลอดภัยดี" not in row.text
