"""contract test ของ `care-tv-adapter` — พิสูจน์สัญญาโดยไม่มี TV จริง

ทุกอย่างในไฟล์นี้รันใน CI ได้ · ไม่มีอุปกรณ์ ไม่มี vendor SDK ไม่มีข้อมูลผู้ป่วยจริง
"""

from __future__ import annotations

import ast
import pathlib
import statistics

import pytest
from core.clock import FakeClock

from adapters.care_tv import actions, inbound, pairing, remote, render, sender
from adapters.care_tv.config import AdapterConfig
from adapters.care_tv.speech import NullSpeaker
from adapters.care_tv.transport import Envelope, InMemoryQueue, PollingTransport, StreamTransport
from care_addons.care_escalation import services as jobs
from care_addons.care_routine import services as routines
from tests.conftest import notifications, scope_for, setup_patient, system_scope

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters" / "care_tv"

# ของที่ adapter ห้ามแตะ — ขอบเขตบังคับด้วยเทส ไม่ใช่ด้วยโฟลเดอร์
FORBIDDEN_IMPORTS = {
    "care_addons.care_careplan",
    "care_addons.care_medication",
    "care_addons.ap_policy",
    "care_addons.ap_approval",
    "care_addons.ap_audit",
    "care_addons.ap_consent",
}


async def _patient_with_reminder(session, tenant, *, quiet_hours=None, severity="medium"):
    patient, _ = await setup_patient(session, tenant, quiet_hours=quiet_hours)
    await routines.add_routine(
        session,
        scope_for(tenant),
        patient_id=patient.patient_id,
        kind="medication",
        label="ยาเช้า",
        scheduled_time="08:00",
        severity=severity,
    )
    patient.channels = ["tv"]
    await session.commit()
    return patient


# ── A) ขอบเขต ────────────────────────────────────────────────────────────────


def test_the_adapter_never_imports_domain_logic():
    """🔒 repo แยกไม่ได้บังคับขอบเขตจริง — repo แยกยัง import ของกันได้ถ้ามีคนติดตั้ง

    ตัวตรวจนี้ฟ้องทันทีที่มีคนข้ามเส้น ซึ่งเป็นเหตุผลที่ scaffold ยังอยู่ใน repo นี้ได้
    """
    leaked: list[str] = []
    for path in sorted(ADAPTER.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN_IMPORTS):
                    leaked.append(f"{path.name}:{node.lineno} → {name}")
    assert not leaked, f"adapter แตะ logic ของโดเมน: {leaked}"


def test_no_vendor_identifier_leaks_into_the_contract():
    """TrueID / Android ห้ามโผล่ในสัญญากลางหรือในโดเมน"""
    vendor = ("trueid", "true_id", "android", "leanback")
    leaked: list[str] = []
    for folder in ("care_addons", "contracts", "policies"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.suffix not in (".py", ".yaml") or "migrations" in path.parts:
                continue
            lowered = path.read_text().lower()
            leaked += [f"{path.name} → {word}" for word in vendor if word in lowered]
    assert not leaked, f"ชื่อ vendor หลุดเข้าสัญญากลาง: {leaked}"


def test_nothing_collects_media_viewing_behaviour():
    """use case ที่ยังรอคำตอบทางกฎหมาย ต้องยังไม่มีร่องรอยในโค้ด"""
    watched = ("watch_duration", "viewing_history", "watch_time", "media_behaviour", "media_behavior")
    leaked: list[str] = []
    for folder in ("care_addons", "adapters", "contracts"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            lowered = path.read_text().lower()
            leaked += [f"{path.name} → {word}" for word in watched if word in lowered]
    assert not leaked, f"มีร่องรอยการเก็บพฤติกรรมการดูสื่อ: {leaked}"


# ── B) สัญญากับ care API จริง ────────────────────────────────────────────────


async def test_the_adapter_registers_without_touching_care_escalation(session, tenant):
    """เกณฑ์รับงานข้อแรก — ไม่แก้โค้ดใน care_escalation แม้บรรทัดเดียว"""
    queue = InMemoryQueue()
    speaker = NullSpeaker()
    sender.install(queue, speaker=speaker)

    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient = await _patient_with_reminder(session, tenant)
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()

        clock.set("2026-08-19T01:00:00+00:00")     # 08:00 ตามเวลาไทย
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

    outbox = await notifications(session, tenant, patient.patient_id)
    assert outbox[0].channel == "tv"
    assert outbox[0].delivery_status == "sent"
    envelopes = queue.drain()
    assert [e.kind for e in envelopes] == ["present"]
    assert envelopes[0].payload["plan"]["needs_answer"] is True
    assert speaker.spoken, "ยาเช้าขอ speak=True จึงต้องมีการอ่านออกเสียง"


async def test_the_adapter_receives_the_domain_decision_and_does_not_redo_it(session, tenant):
    """🔒 quiet hours ถูกตัดสินที่โดเมน · adapter ได้ผลมาแล้วและไม่ประเมินซ้ำ"""
    queue = InMemoryQueue()
    speaker = NullSpeaker()
    sender.install(queue, speaker=speaker)

    with FakeClock("2026-08-18T16:30:00+00:00") as clock:
        patient = await _patient_with_reminder(session, tenant, quiet_hours=("21:00", "07:00"))
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()
        clock.set("2026-08-18T17:00:00+00:00")     # เที่ยงคืนตามเวลาไทย
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

    outbox = await notifications(session, tenant, patient.patient_id)
    if outbox:
        assert outbox[0].presentation["surface"] == "ambient"
        assert outbox[0].presentation["speak"] is False
        assert not speaker.spoken, "quiet hours ลดให้แล้ว adapter ต้องไม่พูด"


def test_render_is_a_pure_function_of_the_intent_it_was_given():
    """ผลของ render ขึ้นกับ intent เท่านั้น — ไม่มีเวลา ไม่มี severity ไม่มี policy"""
    intent = {"surface": "overlay", "speak": True, "response": "required", "dwell": "until_answered"}
    with FakeClock("2026-08-18T17:00:00+00:00"):
        midnight = render.plan(intent)
    with FakeClock("2026-08-19T03:00:00+00:00"):
        midday = render.plan(intent)
    assert midnight == midday
    assert midnight.seconds is None and midnight.needs_answer is True

    quiet = render.plan({**intent, "surface": "ambient", "speak": False, "dwell": "short"})
    assert quiet.region == "corner" and quiet.speak is False and quiet.seconds == 8


async def test_presented_through_the_adapter_still_does_not_close_work(session, tenant):
    """ADR-0014 ข้อ 5 — เส้นทางผ่าน adapter ต้องไม่มีทางอ้อม"""
    sender.install(InMemoryQueue())
    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient = await _patient_with_reminder(session, tenant)
        sysscope = system_scope(tenant)
        await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()
        clock.set("2026-08-19T01:00:00+00:00")
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

        outbox = await notifications(session, tenant, patient.patient_id)
        await inbound.presented(session, scope_for(tenant), outbox[0].id)
        await session.commit()

        open_now = await jobs.open_jobs(session, sysscope, patient.patient_id)
        assert open_now and open_now[0].state == "reminded"
        assert open_now[0].evidence in (None, {})


async def test_remote_keys_map_deterministically_to_the_three_intents(session, tenant):
    sender.install(InMemoryQueue())
    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        patient = await _patient_with_reminder(session, tenant)
        sysscope = system_scope(tenant)
        created = await routines.materialize_day(session, sysscope, patient.patient_id)
        await session.commit()
        clock.set("2026-08-19T01:00:00+00:00")
        await jobs.run_due_jobs(session, sysscope)
        await session.commit()

        job_id = created[0].care_job_id
        patient_scope = scope_for(tenant, patient.patient_id)

        assert await inbound.key_pressed(session, patient_scope, job_id, "BACK") == remote.NOT_YET
        await session.commit()
        still_open = await jobs.open_jobs(session, sysscope, patient.patient_id)
        assert still_open[0].state == "acknowledged", "ยังไม่ได้ทำ = ไม่ปิดงาน"

        assert await inbound.key_pressed(session, patient_scope, job_id, "BUTTON_A") == remote.DONE
        await session.commit()
        # `open_jobs()` คืนทุกงานของผู้ป่วย ไม่ได้กรองเฉพาะที่ยังเปิด — เทียบ state แทน
        closed = await jobs.open_jobs(session, sysscope, patient.patient_id)
        assert [j.state for j in closed] == ["confirmed"]
        assert closed[0].closed_at is not None
        assert closed[0].evidence["kind"] == "patient_confirmed", "หลักฐานมาจากคนกด"


def test_an_unmapped_remote_key_is_refused_instead_of_guessed():
    with pytest.raises(remote.UnmappedKey):
        remote.intent_for("BUTTON_Z")
    assert set(remote.KEY_MAP.values()) <= set(remote.INTENTS)
    assert "dismiss" not in remote.INTENTS, "ไม่มีปุ่มปิด/ไม่สนใจ (ADR-0014 ข้อ 6)"


# ── C) transport + latency ───────────────────────────────────────────────────


async def test_publishing_a_pause_never_waits_for_anyone(session, tenant):
    """🔒 ADR-0015 ข้อ 2 — การหยุดที่ต้องรอใครก่อนเข้าคิว เท่ากับการหยุดที่ไม่หยุด"""
    queue = InMemoryQueue()
    transport = PollingTransport(queue, interval=0.01)
    await transport.publish(Envelope(kind="device_action", payload={"action": "pause"}))
    assert len(queue) == 1, "เข้าคิวทันที ไม่มีขั้นรออนุมัติในเส้นนี้"


async def test_latency_is_bounded_by_the_poll_interval_not_by_policy():
    """SLA จริงของ pause เป็นฟังก์ชันของรอบ poll — วัด ไม่ใช่เดา"""
    from adapters.care_tv.benchmark import _measure

    latencies = await _measure(0.05, 12)
    assert max(latencies) <= 0.05 * 2.5, "latency ต้องไม่เกินรอบ poll อย่างมีนัย"
    assert statistics.median(latencies) <= 0.05, "p50 ควรอยู่ราวครึ่งรอบ"


async def test_stream_transport_refuses_instead_of_pretending():
    """ยังไม่มีชั้นจัดการ connection — ต้องไม่ทำเหมือนมี"""
    with pytest.raises(NotImplementedError, match="ยังไม่มีชั้นจัดการ connection"):
        await StreamTransport(InMemoryQueue()).publish(Envelope(kind="device_action", payload={}))


def test_device_actions_are_a_closed_set():
    controller = actions.RecordingController()
    for action in ("pause", "resume", "cancel"):
        assert actions.execute(controller, action) == action
    assert controller.calls == ["pause", "resume", "cancel"]
    with pytest.raises(actions.UnknownAction):
        actions.execute(controller, "mute")


# ── D) pairing · auth · identity ─────────────────────────────────────────────


def test_credentials_carry_no_patient_data_and_never_print_the_token():
    credential = pairing.DeviceCredential(device_id="tv-001", token="s3cret-token")
    logged = credential.for_log()
    assert "s3cret-token" not in str(logged)
    assert len(logged["token_fingerprint"]) == 12
    assert "patient" not in str(logged).lower()


def test_a_pairing_code_can_be_redacted_before_it_reaches_a_log():
    """กฎ "ห้าม log โค้ด" ที่ไม่มีเครื่องมือช่วย คือกฎที่วันหนึ่งจะมีคนลืม"""
    assert pairing.redact_pairing_code("ใช้โค้ด 428193 บนจอ", "428193") == "ใช้โค้ด *** บนจอ"


def test_config_comes_from_env_and_hides_the_token():
    config = AdapterConfig.from_env(
        {"CARE_TV_API_BASE": "https://care.example", "CARE_TV_TOKEN": "abc", "CARE_TV_DEVICE_ID": "tv-9"}
    )
    assert config.api_base == "https://care.example" and config.device_id == "tv-9"
    assert config.redacted()["token"] == "***"
    assert AdapterConfig.from_env({}).token == "", "ไม่มี default token ที่ใช้งานได้"
