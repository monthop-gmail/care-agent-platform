from __future__ import annotations

from fastapi import APIRouter

from care_addons.ap_audit import services as svc
from care_addons.ap_audit.models import ApAuditEvent
from care_addons.ap_tenancy.deps import ScopeDep, SessionDep

router = APIRouter(prefix="/api/platform/audit", tags=["platform: audit"])


def _serialize(e: ApAuditEvent) -> dict:
    return {
        "event_id": e.event_id,
        "event_type": e.event_type,
        "care_event_type": e.care_event_type,
        "subject_type": e.subject_type,
        "subject_id": e.subject_id,
        "job_id": e.job_id,
        "correlation_id": e.correlation_id,
        "actor": e.actor,
        "occurred_at": e.occurred_at,
        "source": {"kind": e.source_kind, "system": e.source_system},
        "transition": e.transition,
        "policy_result": e.policy_result,
        "severity": e.severity,
        "evidence": e.evidence,
        "attributes": e.attributes,
    }


@router.get("/events")
async def list_events(
    scope: ScopeDep,
    session: SessionDep,
    subject_id: str | None = None,
    care_event_type: str | None = None,
    job_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    events = await svc.query(
        session,
        scope,
        subject_id=subject_id,
        care_event_type=care_event_type,
        job_id=job_id,
        limit=min(limit, 500),
    )
    return [_serialize(e) for e in events]


@router.get("/trail/{correlation_id}")
async def get_trail(correlation_id: str, scope: ScopeDep, session: SessionDep) -> list[dict]:
    """ลำดับเหตุการณ์ทั้งหมดของงานเดียวกัน — ใช้ตอบว่าทำไมระบบถึงทำแบบนั้น"""
    return [_serialize(e) for e in await svc.trail(session, scope, correlation_id)]
