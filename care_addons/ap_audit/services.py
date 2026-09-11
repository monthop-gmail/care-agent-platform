"""ทางเดียวที่ระบบเขียน audit event ได้

โดเมนห้าม insert ตาราง ap_audit_event ตรง ๆ — เรียก emit() เท่านั้น
"""

from __future__ import annotations

import itertools
import re
import time
from typing import Any

from core.clock import now
from core.tenancy import TenantScope, new_id, validate_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit.attributes import problems as attribute_problems
from care_addons.ap_audit.models import ApAuditEvent

# 7 ค่าขั้นต่ำของ event/v1 — ชุดเปิด เพิ่มได้แบบ additive แต่ลบ/เปลี่ยนความหมายไม่ได้
PLATFORM_EVENT_TYPES = {
    # consent/v1 บังคับให้การให้และการเพิกถอนออก event ทุกครั้ง — event/v1 v1.6.0
    # เพิ่งมี event type ให้ใช้ (ไม่มี CONSENT_USED โดยเจตนา · การใช้บันทึกที่ field `consent`)
    "CONSENT_GRANTED",
    "CONSENT_REVOKED",
    "JOB_CREATED",
    "STATE_TRANSITION",
    "GOVERNANCE_DECISION",
    "TASK_ASSIGNED",
    "EXECUTION_STARTED",
    "EXECUTION_FAILED",
    "JOB_COMPLETED",
    # ใบปิดท้ายของ trail — ออกที่ **ทุก terminal** ไม่ใช่เฉพาะที่จบสวย
    # (devfactory-core RFC-0012 · semantics 1.2)
    #
    # 🔒 ต่างจาก JOB_COMPLETED โดยเจตนา:
    #    JOB_COMPLETED = "งานถูกส่งมอบไหม"  (คำแถลงเรื่องผลลัพธ์)
    #    JOB_SETTLED   = "trail นี้จบหรือยัง" (คำแถลงเรื่องบันทึก)
    #    ถ้าใช้ตัวเดียวกัน ผู้อ่านที่นับ JOB_COMPLETED ว่า "สำเร็จ" จะนับยาที่ผู้ป่วยไม่ได้กิน
    #    เป็นความสำเร็จเงียบ ๆ — ซึ่งเป็นสิ่งที่เราทำอยู่จริงก่อนหน้านี้
    "JOB_SETTLED",
}

SUBJECT_TYPES = {
    "job", "execution", "step", "agent", "tool_call", "artifact", "approval", "external",
    # `record` = บันทึกของโดเมนที่ต้องตามรอยได้แต่ไม่ได้เกิดจาก job
    # (agent-platform#14 — เพิ่มเข้า event/v1 หลังเราเจอปัญหาจากการใช้งานจริง)
    "record",
}

FORBIDDEN_ATTRIBUTE_KEYS = {"reasoning", "chain_of_thought", "thinking", "scratchpad"}

# error/v1 — category ที่ platform ใช้ตัดสิน retry policy
ERROR_CATEGORIES = {
    "validation", "authentication", "authorization", "policy_denied", "approval_required",
    "rate_limited", "budget_exceeded", "timeout", "conflict", "provider_error",
    "external_dependency", "internal",
}
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def actor_ref(principal: dict | None) -> dict | None:
    """เหลือแค่ตัวชี้ของ `identity/v1 $defs.Principal` — ตัด `display_name` ทิ้ง

    🔒 ชื่อคนเป็น **เนื้อหา** ไม่ใช่ตัวชี้ (ADR-0011) · `display_name` เป็น optional
       ใน identity/v1 (required มีแค่ type กับ id) การไม่ใส่จึงยัง conform
       และ id ชี้กลับไปที่ตารางผู้ใช้ได้อยู่แล้วสำหรับคนที่มีสิทธิ์อ่านตารางนั้น

    เจอเพราะเอากฎสามบรรทัดของร่าง RFC (agent-platform · dis-65134078 seq 28) มาลอง
    กับ payload จริง — `actor.display_name` ติดมา **ทุกใบ** 112 จาก 112
    """
    if not isinstance(principal, dict):
        return principal
    kept = {k: v for k, v in principal.items() if k != "display_name"}
    if isinstance(kept.get("on_behalf_of"), dict):
        kept["on_behalf_of"] = actor_ref(kept["on_behalf_of"])
    return kept


def make_error(
    code: str, category: str, message: str, *, retryable: bool, **extra: Any
) -> dict:
    """สร้าง error object ที่ conform error/v1

    🔒 `message` ห้ามมี credential / PII / เนื้อหา prompt ของผู้ใช้ (ข้อกำหนดของ error/v1)
    """
    if not ERROR_CODE_PATTERN.match(code):
        raise EventRejected(f"error code ไม่ตรงรูปแบบของ error/v1: {code!r}")
    if category not in ERROR_CATEGORIES:
        raise EventRejected(f"error category ไม่รู้จัก: {category!r}")
    return {"code": code, "category": category, "message": message, "retryable": retryable, **extra}


# ตัวนับลำดับการเขียนของ process นี้ — seed ด้วยเวลาระบบเพื่อให้ค่าหลัง restart ยังเพิ่มขึ้น
_sequence = itertools.count(time.time_ns())


class EventRejected(ValueError):
    """intake ปฏิเสธ — ห้ามเดาค่าที่หายไปให้ (event/v1 invariant)"""


async def emit(
    session: AsyncSession,
    scope: TenantScope,
    *,
    event_type: str,
    subject_type: str,
    subject_id: str,
    care_event_type: str | None = None,
    job_id: str | None = None,
    execution_id: str | None = None,
    agent_id: str | None = None,
    transition: dict | None = None,
    policy_result: dict | None = None,
    severity: str | None = None,
    evidence: dict | None = None,
    attributes: dict[str, Any] | None = None,
    source_kind: str = "internal",
    source_system: str | None = None,
    error: dict | None = None,
    consent: dict | None = None,
) -> ApAuditEvent:
    if not scope.tenant_id:
        raise EventRejected("event ที่ resolve tenant ไม่ได้ ให้ reject ที่ intake — ห้ามเดา tenant ให้")
    if event_type not in PLATFORM_EVENT_TYPES:
        raise EventRejected(
            f"event_type '{event_type}' ไม่อยู่ในชุดของ event/v1 — "
            f"care event ใส่ที่ care_event_type แล้ว map event_type ให้ตรงชนิดของ subject"
        )
    if subject_type not in SUBJECT_TYPES:
        raise EventRejected(f"subject_type '{subject_type}' ไม่อยู่ใน event/v1 $defs.SubjectType")
    if source_kind == "external" and not source_system:
        raise EventRejected("external event ต้องระบุ source_system เสมอ — ต้องรู้ตลอดไปว่ามาจากข้างนอก")
    if subject_type == "job" and job_id is not None and job_id != subject_id:
        raise EventRejected("subject_type=job แล้ว job_id ต้องตรงกับ subject_id (platform_rules)")

    if error is not None:
        missing = {"code", "category", "message", "retryable"} - set(error)
        if missing:
            raise EventRejected(
                f"error ต้องเป็น object ตาม error/v1 — ขาด {sorted(missing)} "
                f"(ใช้ make_error() แทนการส่งข้อความดิบ)"
            )
        # `error/v1` นิยาม `details` ว่า `{"type": "object"}` — เปิดทั้งหมดแบบเดียวกับ
        # `metadata` เป๊ะ · ต่างกันแค่ไม่มีใครพูดถึงมัน · ปิดด้วยทะเบียนเดียวกัน (ADR-0011)
        if found := attribute_problems(error.get("details") or {}):
            raise EventRejected("error.details ไม่ผ่านชุดที่ประกาศไว้ — " + " · ".join(found))

    if transition is not None:
        # event/v1 กำหนด transition.from/to เป็น string — การสร้างของใหม่ที่ยังไม่มีสถานะเดิม
        # ต้องแสดงด้วยการ "ไม่มี key" ไม่ใช่ null (jsonschema ปฏิเสธ null)
        transition = {k: v for k, v in transition.items() if v is not None}

    # ผลการประเมินความยินยอมที่ถูกแช่แข็งไว้ตอนตรวจสิทธิ์ — หยิบครั้งเดียวแล้วหายไป
    #
    # 🔒 อ่านจาก `session.info` แทนการ import `ap_consent` เพราะโมดูลนั้นอยู่ชั้นบนของเรา
    #    (มันเรียก emit() อยู่) — import กลับจะเป็นวงกลม · คีย์เป็นสัญญาระหว่างสองโมดูล
    if consent is None:
        consent = session.info.pop("ap_consent.evaluation", None)
    if consent is not None:
        missing = {"grant_id", "evaluated_at", "satisfied"} - set(consent)
        if missing:
            raise EventRejected(
                f"consent evaluation ต้องเป็น object ตาม consent/v1 $defs.Evaluation — "
                f"ขาด {sorted(missing)}"
            )

    attrs = dict(attributes or {})
    leaked = FORBIDDEN_ATTRIBUTE_KEYS & set(attrs)
    if leaked:
        raise EventRejected(
            f"ห้ามเก็บ private reasoning / chain-of-thought เป็น audit record: {sorted(leaked)}"
        )

    # `attributes` เป็นชุดปิด — audit เก็บตัวชี้ ไม่ใช่เนื้อหา (ADR-0011)
    #
    # 🔒 `event/v1` นิยาม `metadata` ไว้แค่ `{"type": "object"}` ซึ่งเปิดทั้งหมด
    #    ข้อจำกัดนี้เป็นของเราเอง ไม่ใช่ของ platform — เพราะเราเคยเก็บชื่อยาคู่ patient_id
    #    และข้อความที่ส่งให้ผู้ป่วยทั้งประโยคลงที่นี่มาก่อน
    if found := attribute_problems(attrs):
        raise EventRejected("attributes ไม่ผ่านชุดที่ประกาศไว้ — " + " · ".join(found))

    # หลักฐานก็ชี้เหมือนกัน — `evidence.recorded_by` เป็น Principal ตัวเดียวกับ actor
    # บังคับที่นี่ที่เดียว เพราะโดเมนเรียก `as_dict()` กันเจ็ดที่และลืมที่เดียวก็รั่วแล้ว
    if isinstance(evidence, dict) and isinstance(evidence.get("recorded_by"), dict):
        evidence = {**evidence, "recorded_by": actor_ref(evidence["recorded_by"])}

    event = ApAuditEvent(
        event_id=new_id("evt"),
        sequence=next(_sequence),
        event_type=event_type,
        care_event_type=care_event_type,
        tenant_id=validate_id(scope.tenant_id, "tenant_id"),
        workspace_id=scope.workspace_id,
        subject_type=subject_type,
        subject_id=validate_id(subject_id, "subject_id"),
        job_id=job_id,
        execution_id=execution_id,
        agent_id=agent_id,
        correlation_id=scope.correlation_id,
        actor=actor_ref(scope.principal.as_dict()),
        occurred_at=now(),
        source_kind=source_kind,
        source_system=source_system,
        transition=transition,
        policy_result=policy_result,
        severity=severity,
        evidence=evidence,
        attributes=attrs or None,
        error=error,
        consent=consent,
    )
    session.add(event)
    await session.flush()
    return event


def as_platform_event(event: ApAuditEvent, *, lift: tuple[str, ...] = ()) -> dict:
    """แปลงแถวใน DB เป็น payload ตาม `event/v1` ของ agent-platform

    นี่คือรูปแบบที่จะส่งออกนอกระบบ (event bus / consumer อื่น) และเป็นสิ่งที่
    `conformance/payload_check.py` เอาไป validate กับ schema จริงที่ commit ที่ pin ไว้

    `lift` = ชื่อ attribute ของโดเมนที่ต้องการยกขึ้นมาไว้ระดับบนสุด (เช่น id ของ subject
    ที่ contract ส่วนขยายของโดเมนบังคับให้มี) — โมดูลนี้ไม่รู้ว่ามันคืออะไร ผู้เรียกเป็นคนบอก
    เพราะ `ap_*` ห้ามรู้จักคำของโดเมน (ADR-0003 กฎ 1)
    """
    payload: dict[str, Any] = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "tenant_id": event.tenant_id,
        "subject_type": event.subject_type,
        "subject_id": event.subject_id,
        "occurred_at": event.occurred_at.isoformat(),
        "source": {"kind": event.source_kind},
    }
    if event.source_system:
        payload["source"]["system"] = event.source_system
    for field in ("workspace_id", "job_id", "execution_id", "agent_id", "correlation_id"):
        value = getattr(event, field)
        if value is not None:
            payload[field] = value
    if event.actor is not None:
        payload["actor"] = event.actor
    if event.sequence is not None:
        payload["sequence"] = event.sequence
    if event.consent is not None:
        payload["consent"] = event.consent
    if event.transition is not None:
        payload["transition"] = event.transition
    if event.policy_result is not None:
        payload["policy_result"] = event.policy_result
    if event.error is not None:
        payload["error"] = event.error
    if event.attributes:
        payload["metadata"] = event.attributes

    # ส่วนขยายของโดเมน care
    if event.care_event_type is not None:
        payload["care_event_type"] = event.care_event_type
    if event.severity is not None:
        payload["severity"] = event.severity
    if event.evidence is not None:
        payload["evidence"] = event.evidence
    for name in lift:
        value = (event.attributes or {}).get(name)
        if value is not None:
            payload[name] = value
    if event.job_id is not None:
        payload["care_job_id"] = event.job_id
    return payload


async def query(
    session: AsyncSession,
    scope: TenantScope,
    *,
    subject_id: str | None = None,
    care_event_type: str | None = None,
    job_id: str | None = None,
    limit: int = 100,
) -> list[ApAuditEvent]:
    stmt = select(ApAuditEvent).where(ApAuditEvent.tenant_id == scope.tenant_id)
    if subject_id:
        stmt = stmt.where(ApAuditEvent.subject_id == subject_id)
    if care_event_type:
        stmt = stmt.where(ApAuditEvent.care_event_type == care_event_type)
    if job_id:
        stmt = stmt.where(ApAuditEvent.job_id == job_id)
    stmt = stmt.order_by(
        ApAuditEvent.occurred_at.desc(), ApAuditEvent.sequence.desc()
    ).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars())


async def trail(session: AsyncSession, scope: TenantScope, correlation_id: str) -> list[ApAuditEvent]:
    """ตอบคำถาม 'ทำไม agent ถึงส่งข้อความนี้' — ทุก event ของงานเดียวกันเรียงตามเวลา"""
    result = await session.execute(
        select(ApAuditEvent)
        .where(
            ApAuditEvent.tenant_id == scope.tenant_id,
            ApAuditEvent.correlation_id == correlation_id,
        )
        # เรียงด้วยลำดับการเขียนเป็นตัวตัดสินเมื่อเวลาเท่ากัน — ไม่งั้น "อะไรเกิดก่อน" ตอบไม่ได้
        .order_by(ApAuditEvent.occurred_at, ApAuditEvent.sequence)
    )
    return list(result.scalars())
