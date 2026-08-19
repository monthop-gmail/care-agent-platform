"""ทางเดียวที่ระบบเขียน audit event ได้

โดเมนห้าม insert ตาราง ap_audit_event ตรง ๆ — เรียก emit() เท่านั้น
"""

from __future__ import annotations

import re
from typing import Any

from core.clock import now
from core.tenancy import TenantScope, new_id, validate_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit.models import ApAuditEvent

# 7 ค่าขั้นต่ำของ event/v1 — ชุดเปิด เพิ่มได้แบบ additive แต่ลบ/เปลี่ยนความหมายไม่ได้
PLATFORM_EVENT_TYPES = {
    "JOB_CREATED",
    "STATE_TRANSITION",
    "GOVERNANCE_DECISION",
    "TASK_ASSIGNED",
    "EXECUTION_STARTED",
    "EXECUTION_FAILED",
    "JOB_COMPLETED",
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

    if transition is not None:
        # event/v1 กำหนด transition.from/to เป็น string — การสร้างของใหม่ที่ยังไม่มีสถานะเดิม
        # ต้องแสดงด้วยการ "ไม่มี key" ไม่ใช่ null (jsonschema ปฏิเสธ null)
        transition = {k: v for k, v in transition.items() if v is not None}

    attrs = dict(attributes or {})
    leaked = FORBIDDEN_ATTRIBUTE_KEYS & set(attrs)
    if leaked:
        raise EventRejected(
            f"ห้ามเก็บ private reasoning / chain-of-thought เป็น audit record: {sorted(leaked)}"
        )

    event = ApAuditEvent(
        event_id=new_id("evt"),
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
        actor=scope.principal.as_dict(),
        occurred_at=now(),
        source_kind=source_kind,
        source_system=source_system,
        transition=transition,
        policy_result=policy_result,
        severity=severity,
        evidence=evidence,
        attributes=attrs or None,
        error=error,
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
    stmt = stmt.order_by(ApAuditEvent.occurred_at.desc()).limit(limit)
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
        .order_by(ApAuditEvent.occurred_at)
    )
    return list(result.scalars())
