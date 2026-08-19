"""หน้าตาที่คนใช้ตัดสิน — **ไม่มี endpoint ที่ APPROVE ได้โดยไม่มีคนกด**

`POST /decide` ต้องมีสิทธิ์ `platform.approval.decide` และ authority คือผู้ใช้ที่ล็อกอินอยู่จริง
ผู้เรียกส่ง authority มาเองไม่ได้ — ไม่งั้นการอนุมัติจะสวมรอยกันได้
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from addons.tenancy.deps import ScopeDep, SessionDep
from core.auth import require_permission
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from care_addons.ap_approval import services as svc

router = APIRouter(prefix="/api/platform/approvals", tags=["platform: approval"])


def principal_of(user: Any) -> dict:
    return {
        "type": "human",
        "id": f"user-{user.id}",
        "display_name": getattr(user, "full_name", "") or getattr(user, "email", ""),
    }


class DecisionIn(BaseModel):
    decision: str = Field(description="APPROVE | REJECT | REQUIRE_CHANGES")
    reason: str = Field(min_length=1)
    valid_for_hours: int | None = Field(default=None, ge=1, le=24 * 30)


def _request_out(r: Any) -> dict:
    return {
        "request_id": r.request_id,
        "capability": r.capability,
        "action_risk": r.action_risk,
        "authority_required": r.authority_required,
        "subject": {"type": r.subject_type, "id": r.subject_id},
        "summary": r.summary,
        "proposed": r.proposed,
        "requested_by": r.requested_by,
        "requested_at": r.requested_at.isoformat() if r.requested_at else None,
        "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        "state": r.state,
    }


@router.get("")
async def list_pending(
    scope: ScopeDep,
    session: SessionDep,
    _: Annotated[Any, Depends(require_permission("platform.approval.read"))],
) -> list[dict]:
    return [_request_out(r) for r in await svc.pending_requests(session, scope)]


@router.post("/{request_id}/decide")
async def decide(
    request_id: str,
    body: DecisionIn,
    scope: ScopeDep,
    session: SessionDep,
    user: Annotated[Any, Depends(require_permission("platform.approval.decide"))],
) -> dict:
    try:
        row = await svc.decide(
            session,
            scope,
            request_id=request_id,
            decision=body.decision,
            reason=body.reason,
            # 🔒 authority มาจาก session ของผู้ใช้เท่านั้น ไม่รับจาก body
            authority=principal_of(user),
            valid_for=timedelta(hours=body.valid_for_hours) if body.valid_for_hours else None,
        )
    except svc.ApprovalRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return {
        "approval_id": row.approval_id,
        "request_id": row.request_id,
        "decision": row.decision,
        "decided_at": row.decided_at.isoformat(),
        "supersedes": row.supersedes,
    }
