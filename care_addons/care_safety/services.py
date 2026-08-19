"""รับสัญญาณจากโลกจริงเข้าระบบ — แล้วตัดสินว่าจะปลุกใครไหม

    "ออกจากบ้านผิดเวลา · เดินออกนอกพื้นที่ปลอดภัย · ล้ม · ไม่ตอบสนอง · เปิดเตาทิ้งไว้"

🔒 กติกาของ `contracts/safety/v1` ที่บังคับด้วยโค้ด:
   1. sensor รายงาน **สิ่งที่วัดได้** ไม่ใช่การวินิจฉัย — ข้อความทุกบรรทัดพูดถึงสัญญาณ ไม่ใช่อาการ
   2. external event ต้องคง source ไว้ตลอดไป ห้ามแปลงเป็น internal
   3. confidence ต่ำกว่าเกณฑ์ → บันทึกไว้แต่ห้าม escalate อัตโนมัติ (กัน false safety alert)
   4. สัญญาณเดิมซ้ำในหน้าต่างเดียวกัน = เหตุการณ์เดียว ห้ามปลุกซ้ำ (กัน notification storm)
   5. **ไม่มีสัญญาณ ≠ ปลอดภัย** — จึงไม่มีฟังก์ชันไหนที่ตอบว่า "ทุกอย่างปกติ"
   6. critical เท่านั้นที่ข้าม quiet hours และต้องแจ้งผู้ป่วยย้อนหลังเสมอ
"""

from __future__ import annotations

from datetime import datetime, timedelta

from core.clock import now
from core.tenancy import Principal, TenantScope, new_id, scoped
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action
from care_addons.care_escalation import services as escalation
from care_addons.care_patient.services import feature_enabled, get_patient
from care_addons.care_safety import policy as safety_policy
from care_addons.care_safety.models import EVENT_KINDS, SOURCE_KINDS, CareSafetyEvent

OPEN_STATES = ("detected", "acknowledged")


class SafetyRuleViolation(PermissionError):
    """กติกาของสัญญาณความปลอดภัย — ไม่ใช่ error ธรรมดา"""


def _describe(event: CareSafetyEvent) -> str:
    """ข้อความที่ผู้ดูแลได้อ่าน — 🔒 พูดถึงสัญญาณและอุปกรณ์ ไม่ใช่สภาพของผู้ป่วย"""
    what = {
        "fall_suspected": "อุปกรณ์รายงานรูปแบบการเคลื่อนไหวที่เข้าเกณฑ์การล้ม",
        "left_home_unexpectedly": "อุปกรณ์รายงานว่าออกจากบ้านนอกเวลาปกติ",
        "outside_safe_area": "ตำแหน่งที่อุปกรณ์รายงานอยู่นอกพื้นที่ที่ตั้งไว้",
        "not_returned_home": "ยังไม่มีสัญญาณว่ากลับถึงบ้านตามเวลาที่ตั้งไว้",
        "no_response": "ไม่มีการตอบสนองต่อการเรียกจากอุปกรณ์",
        "stove_left_on": "อุปกรณ์รายงานว่าเตายังเปิดอยู่",
        "door_left_open": "เซ็นเซอร์ประตูรายงานว่าประตูเปิดค้าง",
        "long_time_in_bathroom": "เซ็นเซอร์รายงานว่าอยู่ในห้องน้ำนานกว่าปกติ",
        "device_offline": "อุปกรณ์ขาดการเชื่อมต่อ",
    }.get(event.kind, f"สัญญาณ '{event.kind}'")
    source = (event.source or {}).get("system", "อุปกรณ์")
    when = event.observed_at.strftime("%H:%M")
    text = f"{what} เวลา {when} (จาก {source})"
    if event.confidence is not None:
        text += f" · ความมั่นใจของอุปกรณ์ {event.confidence:.0%}"
    return text


async def _recent_duplicate(
    session: AsyncSession, scope: TenantScope, *, patient_id: str, kind: str, observed_at: datetime
) -> CareSafetyEvent | None:
    window = timedelta(minutes=safety_policy.load().dedup_window_minutes)
    result = await session.execute(
        scoped(
            select(CareSafetyEvent)
            .where(
                CareSafetyEvent.patient_id == patient_id,
                CareSafetyEvent.kind == kind,
                CareSafetyEvent.observed_at >= observed_at - window,
                CareSafetyEvent.state.in_(OPEN_STATES),
            )
            .order_by(CareSafetyEvent.observed_at.desc()),
            CareSafetyEvent,
            scope,
        )
    )
    return result.scalars().first()


@care_action("safety.signal.intake", autonomous=True)
async def report_signal(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    kind: str,
    source: dict,
    observed_at: datetime | None = None,
    confidence: float | None = None,
    raw: dict | None = None,
) -> CareSafetyEvent:
    """รับสัญญาณเข้าระบบ — บันทึกเสมอ · ปลุกคนเฉพาะเมื่อผ่านเกณฑ์"""
    patient = await get_patient(session, scope, patient_id, required_scope="care.manage")
    if kind not in EVENT_KINDS:
        raise ValueError(f"kind ไม่รู้จัก: {kind} — ต้องเป็นหนึ่งใน {EVENT_KINDS}")
    if not isinstance(source, dict) or source.get("kind") not in SOURCE_KINDS:
        raise ValueError(f"source.kind ต้องเป็นหนึ่งใน {SOURCE_KINDS}")
    if not source.get("system"):
        # 🔒 event/v1: external event ต้องระบุ source_system เสมอ
        raise ValueError("source.system หายไป — ต้องรู้ตลอดไปว่าสัญญาณนี้มาจากระบบไหน")
    if confidence is not None and not 0 <= confidence <= 1:
        raise ValueError("confidence ต้องอยู่ระหว่าง 0 ถึง 1")
    if not feature_enabled(patient, "safety"):
        raise SafetyRuleViolation("care_profile.safety ยังปิดอยู่สำหรับผู้ป่วยรายนี้")

    moment = observed_at or now()
    pol = safety_policy.load()

    duplicate = await _recent_duplicate(
        session, scope, patient_id=patient_id, kind=kind, observed_at=moment
    )
    if duplicate is not None:
        # 🔒 สัญญาณเดิมในหน้าต่างเดียวกัน = เหตุการณ์เดียว — นับเพิ่มแต่ไม่ปลุกซ้ำ
        duplicate.repeat_count += 1
        await session.flush()
        await audit.emit(
            session,
            _event_scope(scope, duplicate),
            event_type="STATE_TRANSITION",
            subject_type="record",
            subject_id=duplicate.safety_event_id,
            care_event_type="care.safety.detected",
            severity=duplicate.severity,
            source_kind="external",
            source_system=str(source["system"]),
            transition={"from": duplicate.state, "to": duplicate.state, "reason": "สัญญาณซ้ำในหน้าต่างเดียวกัน"},
            attributes={
                "record_type": "safety_event",
                "patient_id": patient_id,
                "kind": kind,
                "repeat_count": duplicate.repeat_count,
                "aggregated": True,
            },
        )
        return duplicate

    event = CareSafetyEvent(
        safety_event_id=new_id("saf"),
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        kind=kind,
        source={k: v for k, v in source.items() if v is not None},
        confidence=confidence,
        observed_at=moment,
        severity=pol.severity_for(kind),
        state="detected",
        raw=raw,
        correlation_id=scope.correlation_id or new_id("corr"),
        recorded_at=now(),
    )
    session.add(event)
    await session.flush()

    event_scope = _event_scope(scope, event)
    await audit.emit(
        session,
        event_scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=event.safety_event_id,
        care_event_type="care.safety.detected",
        severity=event.severity,
        # 🔒 มาจากข้างนอก — ต้องรู้ตลอดไป ห้ามแปลงเป็น internal (event/v1)
        source_kind="external",
        source_system=str(source["system"]),
        evidence={"kind": "device_reported", "recorded_by": {"type": "service", "id": str(source["system"])}},
        transition={"to": "detected", "reason": kind},
        attributes={
            "record_type": "safety_event",
            "patient_id": patient_id,
            "kind": kind,
            "source_kind": source["kind"],
            "device_id": source.get("device_id"),
            "confidence": confidence,
        },
    )

    if not pol.may_escalate(confidence):
        # 🔒 บันทึกไว้ แต่ไม่ปลุกใคร — และต้องเห็นได้ว่าทำไมถึงไม่ปลุก
        await audit.emit(
            session,
            event_scope,
            event_type="EXECUTION_FAILED",
            subject_type="record",
            subject_id=event.safety_event_id,
            severity="low",
            error=audit.make_error(
                "care.safety.below_confidence_threshold",
                "validation",
                f"อุปกรณ์แจ้งความมั่นใจ {confidence} ต่ำกว่าเกณฑ์ {pol.min_confidence} "
                f"— บันทึกไว้แต่ยังไม่แจ้งผู้ดูแล",
                retryable=False,
            ),
            attributes={"patient_id": patient_id, "kind": kind, "confidence": confidence},
        )
        return event

    await _alert(session, event_scope, event)
    return event


def _event_scope(scope: TenantScope, event: CareSafetyEvent) -> TenantScope:
    if scope.correlation_id == event.correlation_id:
        return scope
    return TenantScope(
        tenant_id=scope.tenant_id,
        principal=scope.principal,
        workspace_id=scope.workspace_id,
        correlation_id=event.correlation_id,
    )


async def _alert(session: AsyncSession, scope: TenantScope, event: CareSafetyEvent) -> None:
    """แจ้งผู้ดูแล — critical แจ้งทุกคน ระดับอื่นแจ้งคนแรกตามลำดับ"""
    capability = "emergency.escalate" if event.severity == "critical" else "caregiver.notify"
    sent = await escalation.send_to_caregivers(
        session,
        scope,
        patient_id=event.patient_id,
        text=_describe(event),
        capability=capability,
        severity=event.severity,
        all_targets=event.severity == "critical",
    )
    event.escalated = bool(sent)
    await session.flush()


@care_action("safety.signal.intake", autonomous=True)
async def acknowledge(
    session: AsyncSession,
    scope: TenantScope,
    safety_event_id: str,
    *,
    acknowledged_by: Principal,
    note: str = "",
) -> CareSafetyEvent:
    """ผู้ดูแลรับเรื่องแล้ว — 🔒 คนเท่านั้น เพราะการรับเรื่องคือการรับผิดชอบ"""
    if acknowledged_by.type != "human":
        raise SafetyRuleViolation(
            f"สัญญาณความปลอดภัยรับเรื่องได้โดยคนเท่านั้น — ได้รับ '{acknowledged_by.type}'"
        )
    event = await get_event(session, scope, safety_event_id)
    if event.state in ("resolved", "dismissed"):
        return event

    previous = event.state
    event.state = "acknowledged"
    event.acknowledged_by = acknowledged_by.as_dict()
    event.acknowledged_at = now()
    event.resolution_note = note or None
    await session.flush()

    await audit.emit(
        session,
        _event_scope(scope, event),
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=event.safety_event_id,
        care_event_type="care.safety.acknowledged",
        severity=event.severity,
        evidence={"kind": "caregiver_confirmed", "recorded_by": acknowledged_by.as_dict()},
        transition={"from": previous, "to": "acknowledged", "reason": note or "ผู้ดูแลรับเรื่อง"},
        attributes={
            "record_type": "safety_event",
            "patient_id": event.patient_id,
            "kind": event.kind,
        },
    )
    return event


@care_action("safety.signal.intake", autonomous=True)
async def close_event(
    session: AsyncSession,
    scope: TenantScope,
    safety_event_id: str,
    *,
    state: str,
    closed_by: Principal,
    note: str = "",
) -> CareSafetyEvent:
    """ปิดเรื่อง — `resolved` (จัดการแล้ว) หรือ `dismissed` (สัญญาณผิดพลาด)

    🔒 `dismissed` ไม่ลบ event ทิ้ง — อุปกรณ์ที่แจ้งผิดบ่อยต้องนับได้ว่าผิดกี่ครั้ง
    """
    if state not in ("resolved", "dismissed"):
        raise ValueError("state ต้องเป็น resolved หรือ dismissed")
    if closed_by.type != "human":
        raise SafetyRuleViolation("ปิดเรื่องความปลอดภัยได้โดยคนเท่านั้น")

    event = await get_event(session, scope, safety_event_id)
    previous = event.state
    event.state = state
    event.resolution_note = note or event.resolution_note
    await session.flush()

    await audit.emit(
        session,
        _event_scope(scope, event),
        event_type="JOB_COMPLETED",
        subject_type="record",
        subject_id=event.safety_event_id,
        care_event_type="care.safety.acknowledged",
        severity=event.severity,
        evidence={"kind": "caregiver_confirmed", "recorded_by": closed_by.as_dict()},
        transition={"from": previous, "to": state, "reason": note or state},
        attributes={
            "record_type": "safety_event",
            "patient_id": event.patient_id,
            "kind": event.kind,
            "repeat_count": event.repeat_count,
        },
    )
    return event


async def get_event(
    session: AsyncSession, scope: TenantScope, safety_event_id: str
) -> CareSafetyEvent:
    result = await session.execute(
        scoped(
            select(CareSafetyEvent).where(CareSafetyEvent.safety_event_id == safety_event_id),
            CareSafetyEvent,
            scope,
        )
    )
    event = result.scalars().first()
    if event is None:
        raise LookupError(f"ไม่พบสัญญาณ {safety_event_id}")
    return event


async def open_events(
    session: AsyncSession, scope: TenantScope, patient_id: str
) -> list[CareSafetyEvent]:
    """สัญญาณที่ยังไม่ปิด — 🔒 ว่างเปล่าไม่ได้แปลว่า "ปลอดภัย" (safety_rules ข้อ 5)"""
    result = await session.execute(
        scoped(
            select(CareSafetyEvent)
            .where(
                CareSafetyEvent.patient_id == patient_id,
                CareSafetyEvent.state.in_(OPEN_STATES),
            )
            .order_by(CareSafetyEvent.observed_at.desc()),
            CareSafetyEvent,
            scope,
        )
    )
    return list(result.scalars())


def as_safety_event(event: CareSafetyEvent) -> dict:
    """payload ตาม `contracts/safety/v1`"""
    payload = {
        "safety_event_id": event.safety_event_id,
        "tenant_id": event.tenant_id,
        "patient_id": event.patient_id,
        "kind": event.kind,
        "source": event.source,
        "observed_at": event.observed_at.isoformat(),
        "severity": event.severity,
        "state": event.state,
        "acknowledged_at": event.acknowledged_at.isoformat() if event.acknowledged_at else None,
    }
    if event.confidence is not None:
        payload["confidence"] = event.confidence
    if event.acknowledged_by:
        payload["acknowledged_by"] = {k: v for k, v in event.acknowledged_by.items() if v}
    if event.raw:
        payload["raw"] = event.raw
    return payload
