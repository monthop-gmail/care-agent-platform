"""ทางเดียวที่ระบบเขียน audit event ได้

โดเมนห้าม insert ตาราง ap_audit_event ตรง ๆ — เรียก emit() เท่านั้น
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit.models import ApAuditEvent
from care_addons.ap_tenancy.clock import now
from care_addons.ap_tenancy.ids import new_id, validate_id
from care_addons.ap_tenancy.services import TenantScope

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

SUBJECT_TYPES = {"job", "execution", "step", "agent", "tool_call", "artifact", "approval", "external"}

FORBIDDEN_ATTRIBUTE_KEYS = {"reasoning", "chain_of_thought", "thinking", "scratchpad"}


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
    error: str | None = None,
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
