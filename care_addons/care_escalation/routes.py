from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from care_addons.ap_tenancy.deps import ScopeDep, SessionDep
from care_addons.ap_tenancy.services import scoped
from care_addons.care_escalation import services as svc
from care_addons.care_escalation.models import CareJob, CareNotification

router = APIRouter(prefix="/api/care/jobs", tags=["care: jobs"])


class AckIn(BaseModel):
    done: bool = True
    evidence_kind: str = "patient_confirmed"


def _serialize(job: CareJob) -> dict:
    return {
        "care_job_id": job.care_job_id,
        "patient_id": job.patient_id,
        "source_kind": job.source_kind,
        "source_id": job.source_id,
        "label": job.label,
        "state": job.state,
        "severity": job.severity,
        "due_at": job.due_at,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "next_attempt_at": job.next_attempt_at,
        "correlation_id": job.correlation_id,
        "evidence": job.evidence,
    }


@router.get("")
async def list_jobs(
    scope: ScopeDep, session: SessionDep, patient_id: str, state: str | None = None
) -> list[dict]:
    jobs = await svc.open_jobs(session, scope, patient_id, states=[state] if state else None)
    return [_serialize(j) for j in jobs]


@router.post("/{care_job_id}/acknowledge")
async def acknowledge(care_job_id: str, body: AckIn, scope: ScopeDep, session: SessionDep) -> dict:
    try:
        job = await svc.acknowledge(
            session, scope, care_job_id, evidence_kind=body.evidence_kind, done=body.done
        )
    except svc.JobNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return _serialize(job)


@router.post("/{care_job_id}/caregiver-acknowledge")
async def caregiver_acknowledge(care_job_id: str, scope: ScopeDep, session: SessionDep) -> dict:
    try:
        job = await svc.caregiver_acknowledge(session, scope, care_job_id)
    except svc.JobNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return _serialize(job)


@router.post("/tick")
async def tick(scope: ScopeDep, session: SessionDep) -> dict:
    """เดินเครื่อง closed loop หนึ่งรอบ — ปกติ ARQ worker เป็นคนเรียก เปิดไว้ให้ทดสอบ/ตรวจสอบได้"""
    summary = await svc.run_due_jobs(session, scope)
    await session.commit()
    return summary


@router.get("/notifications")
async def list_notifications(
    scope: ScopeDep, session: SessionDep, patient_id: str, audience: str | None = None
) -> list[dict]:
    stmt = select(CareNotification).where(CareNotification.patient_id == patient_id)
    if audience:
        stmt = stmt.where(CareNotification.audience == audience)
    result = await session.execute(
        scoped(stmt.order_by(CareNotification.sent_at.desc()), CareNotification, scope)
    )
    return [
        {
            "id": n.id,
            "audience": n.audience,
            "target": n.target_principal_id,
            "channel": n.channel,
            "text": n.text,
            "severity": n.severity,
            "care_job_id": n.care_job_id,
            "aggregated_count": n.aggregated_count,
            "sent_at": n.sent_at,
            # "บันทึกว่าส่ง" กับ "ส่งถึงจริง" เป็นคนละเรื่อง — ผู้ดูแลต้องเห็นความต่างนี้
            "delivery_status": n.delivery_status,
            "delivery_error": n.delivery_error,
        }
        for n in result.scalars()
    ]
