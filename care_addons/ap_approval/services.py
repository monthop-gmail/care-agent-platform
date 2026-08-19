"""ทางเดียวที่ระบบสร้างคำขออนุมัติและบันทึกคำตัดสินได้ — conform `approval/v1`

โดเมนห้าม insert ตาราง ap_approval* ตรง ๆ

🔒 กติกาที่บังคับด้วยโค้ด ไม่ใช่ด้วยความตั้งใจ:
   1. **ไม่มี auto-approve** — ไม่มีทางเดียวในไฟล์นี้ที่เขียน APPROVE ได้โดยไม่มี `authority`
      ที่เป็นคน คำขอที่รอนานเกินกำหนดกลายเป็น `expired` (งานไม่เดิน) ไม่ใช่ `approved`
   2. **decision immutable** — ไม่มี UPDATE บนตาราง ap_approval เปลี่ยนใจ = ใบใหม่ที่ `supersedes` ใบเดิม
   3. **no agent has total authority** — agent อนุมัติงานที่ตัวเองยื่นไม่ได้
   4. ทุกคำตัดสินมี audit event GOVERNANCE_DECISION คู่กันเสมอ

🔒 โมดูลนี้ห้ามรู้จักคำของโดเมน (ADR-0003 กฎ 1) — สิ่งที่ขออนุมัติคือ `subject` เฉย ๆ
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from core.clock import now
from core.tenancy import TenantScope, new_id, validate_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_approval.models import (
    DECISIONS,
    SUBJECT_TYPES,
    ApApproval,
    ApApprovalRequest,
)
from care_addons.ap_audit import services as audit

# ⚠️ เข้มกว่า approval/v1 โดยตั้งใจ — contract ห้ามแค่ "agent อนุมัติงานของตัวเอง"
# ที่นี่ตัดสินใจว่า **คนเท่านั้น** ที่ออกคำตัดสินได้ เพราะ consumer นี้มี action ที่กระทบคน
# (ADR-0006) contract เป็นพื้น ผู้บริโภคตั้งให้เข้มขึ้นได้ แต่ลดลงไม่ได้
DECIDING_PRINCIPAL_TYPES = {"human"}


# ── สิ่งที่เกิดขึ้นเมื่ออนุมัติ ────────────────────────────────────────────────
# 🔒 โมดูลนี้ไม่รู้ว่า capability หนึ่ง ๆ ทำอะไร — โดเมนลงทะเบียนผลของการอนุมัติเอง
#    (รูปแบบเดียวกับ sender registry ของ care_escalation) ทำให้ ap_approval ยังไม่มี
#    คำของโดเมนอยู่ในโค้ดเลยแม้แต่คำเดียว ตาม ADR-0003 กฎ 1
_APPLIERS: dict[str, Any] = {}


def register_applier(capability: str, applier: Any) -> None:
    """applier(session, scope, request, approval) -> None

    ทำงาน **ใน transaction เดียวกับคำตัดสิน** — ถ้า applier ล้ม คำตัดสินต้องล้มตาม
    ไม่งั้นจะมีใบอนุมัติที่ไม่มีผลจริงค้างอยู่ในระบบ
    """
    _APPLIERS[capability] = applier


def applier_for(capability: str) -> Any:
    return _APPLIERS.get(capability)


class ApprovalRejected(ValueError):
    """คำขอหรือคำตัดสินผิดกติกา — ห้ามเดาค่าที่หายไปให้"""


def _check_principal(principal: Any, *, field: str) -> dict:
    if not isinstance(principal, dict):
        raise ApprovalRejected(f"{field} ต้องเป็น Principal ของ identity/v1 (object ที่มี type และ id)")
    ptype, pid = principal.get("type"), principal.get("id")
    if ptype not in ("human", "agent", "service"):
        raise ApprovalRejected(f"{field}.type ไม่อยู่ใน identity/v1 $defs.Principal: {ptype!r}")
    if not isinstance(pid, str) or not pid:
        raise ApprovalRejected(f"{field}.id หายไป — audit ต้องตอบได้เสมอว่าใคร")
    return {k: v for k, v in principal.items() if v is not None}


async def request_approval(
    session: AsyncSession,
    scope: TenantScope,
    *,
    decision: Any,
    subject_type: str,
    subject_id: str,
    summary: str,
    requested_by: dict,
    proposed: dict | None = None,
    expires_in: timedelta | None = None,
    correlation_id: str | None = None,
) -> ApApprovalRequest:
    """ยื่นคำขอ — `decision` คือผลจาก policy engine ที่บอกว่าทำไมต้องขอ

    คำขอที่ policy บอกว่าไม่ต้องขออนุมัติ ถือว่าเป็นความผิดพลาดของผู้เรียก:
    การสร้างคำขอที่ไม่จำเป็นทำให้คนชินกับการกดอนุมัติ ซึ่งทำลายคุณค่าของด่านนี้
    """
    if not scope.tenant_id:
        raise ApprovalRejected("คำขอที่ resolve tenant ไม่ได้ ให้ reject — ห้ามเดา tenant ให้")
    if subject_type not in SUBJECT_TYPES:
        raise ApprovalRejected(f"subject_type '{subject_type}' ไม่อยู่ใน approval/v1 $.subject.type")
    validate_id(subject_id)
    if not getattr(decision, "requires_human", False):
        raise ApprovalRejected(
            f"policy ตัดสินว่า '{getattr(decision, 'capability', '?')}' ไม่ต้องขออนุมัติ "
            f"(authority={getattr(decision, 'authority', '?')}) — คำขอที่ไม่จำเป็นทำให้คนกดอนุมัติโดยไม่อ่าน"
        )
    if not summary.strip():
        raise ApprovalRejected("summary ว่างไม่ได้ — ผู้ตัดสินต้องเห็นว่ากำลังอนุมัติอะไร")

    req = ApApprovalRequest(
        request_id=new_id("apr"),
        tenant_id=scope.tenant_id,
        workspace_id=getattr(scope, "workspace_id", None),
        capability=decision.capability,
        action_risk=decision.action_risk,
        authority_required=decision.authority,
        policy_id=decision.policy_id,
        subject_type=subject_type,
        subject_id=subject_id,
        summary=summary.strip(),
        proposed=proposed,
        requested_by=_check_principal(requested_by, field="requested_by"),
        requested_at=now(),
        expires_at=(now() + expires_in) if expires_in else None,
        state="pending",
        correlation_id=correlation_id,
    )
    session.add(req)
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="TASK_ASSIGNED",
        subject_type="approval",
        subject_id=req.request_id,
        policy_result=decision.as_policy_result(),
        attributes={
            "capability": decision.capability,
            "authority_required": decision.authority,
            "subject_ref": f"{subject_type}:{subject_id}",
            "summary": req.summary,
        },
    )
    return req


async def decide(
    session: AsyncSession,
    scope: TenantScope,
    *,
    request_id: str,
    decision: str,
    reason: str,
    authority: dict,
    valid_for: timedelta | None = None,
) -> ApApproval:
    """บันทึกคำตัดสิน — ใบเก่าไม่ถูกแก้ ใบใหม่ `supersedes` ใบเดิม"""
    if decision not in DECISIONS:
        raise ApprovalRejected(
            f"decision '{decision}' ไม่อยู่ในชุดปิดของ approval/v1 {DECISIONS} "
            f"— การเพิ่มค่าใหม่ต้องมี RFC ที่ devfactory-core ก่อน"
        )
    if not reason or not reason.strip():
        raise ApprovalRejected("reason ว่างไม่ได้ — ต้องตอบได้เสมอว่าตัดสินอย่างนั้นเพราะอะไร")
    who = _check_principal(authority, field="authority")
    if who["type"] not in DECIDING_PRINCIPAL_TYPES:
        raise ApprovalRejected(
            f"authority.type={who['type']!r} ออกคำตัดสินไม่ได้ — ที่นี่คนเท่านั้นที่อนุมัติได้ (ADR-0006)"
        )

    req = (
        await session.execute(
            select(ApApprovalRequest).where(
                ApApprovalRequest.request_id == request_id,
                ApApprovalRequest.tenant_id == scope.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if req is None:
        raise ApprovalRejected(f"ไม่พบคำขอ {request_id} ใน tenant นี้")
    if req.state in ("expired", "withdrawn"):
        raise ApprovalRejected(
            f"คำขอนี้อยู่สถานะ {req.state} แล้ว — ต้องยื่นใหม่ ไม่ใช่ตัดสินใบเดิม"
        )
    # 🔒 no agent has total authority — ผู้ยื่นตัดสินให้ตัวเองไม่ได้
    if who["id"] == req.requested_by.get("id"):
        raise ApprovalRejected("ผู้ยื่นคำขอตัดสินคำขอของตัวเองไม่ได้ (approval/v1 invariant)")

    previous = (
        await session.execute(
            select(ApApproval)
            .where(ApApproval.request_id == request_id, ApApproval.tenant_id == scope.tenant_id)
            .order_by(ApApproval.decided_at.desc())
        )
    ).scalars().first()

    row = ApApproval(
        approval_id=new_id("apv"),
        tenant_id=scope.tenant_id,
        workspace_id=req.workspace_id,
        request_id=req.request_id,
        subject_type=req.subject_type,
        subject_id=req.subject_id,
        decision=decision,
        reason=reason.strip(),
        authority=who,
        decided_at=now(),
        policy_id=req.policy_id,
        action_risk=req.action_risk,
        expires_at=(now() + valid_for) if valid_for else None,
        supersedes=previous.approval_id if previous else None,
    )
    session.add(row)
    req.state = {
        "APPROVE": "approved",
        "REJECT": "rejected",
        "REQUIRE_CHANGES": "changes_requested",
    }[decision]
    await session.flush()

    # 🔒 approval/v1: ทุก APPROVE ต้องมี GOVERNANCE_DECISION คู่กันเสมอ — ที่นี่ออกให้ทุกคำตัดสิน
    await audit.emit(
        session,
        scope,
        event_type="GOVERNANCE_DECISION",
        subject_type="approval",
        subject_id=row.approval_id,
        policy_result={
            "effect": "allow" if decision == "APPROVE" else "deny",
            "authority": req.authority_required,
            "action_risk": req.action_risk,
            "policy_id": req.policy_id,
        },
        transition={"from": "pending", "to": req.state},
        attributes={
            "decision": decision,
            "reason": row.reason,
            "authority_type": who["type"],
            "authority_id": who["id"],
            "capability": req.capability,
            "subject_ref": f"{req.subject_type}:{req.subject_id}",
            "request_id": req.request_id,
            "supersedes": row.supersedes,
        },
    )

    if decision == "APPROVE":
        applier = applier_for(req.capability)
        if applier is not None:
            # ตั้งใจไม่ดัก exception — ใบอนุมัติที่ไม่มีผลจริงอันตรายกว่าการที่ผู้กดเห็น error
            await applier(session, scope, req, row)
    return row


async def withdraw(
    session: AsyncSession,
    scope: TenantScope,
    *,
    request_id: str,
    reason: str,
    by: dict,
) -> ApApprovalRequest | None:
    """ถอนคำขอที่ไม่ต้องตัดสินแล้ว เพราะเรื่องจบไปทางอื่น

    🔒 `withdrawn` **ไม่ใช่** `approved` — มันแปลว่า "ไม่ต้องตัดสิน" ไม่ใช่ "ตัดสินว่าให้ผ่าน"
    ไม่มีทางที่ path นี้จะทำให้เกิดใบอนุมัติ เพราะมันไม่แตะตาราง ap_approval เลย
    """
    who = _check_principal(by, field="by")
    req = (
        await session.execute(
            select(ApApprovalRequest).where(
                ApApprovalRequest.request_id == request_id,
                ApApprovalRequest.tenant_id == scope.tenant_id,
                ApApprovalRequest.state == "pending",
            )
        )
    ).scalar_one_or_none()
    if req is None:
        return None
    req.state = "withdrawn"
    await session.flush()
    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="approval",
        subject_id=req.request_id,
        transition={"from": "pending", "to": "withdrawn"},
        attributes={"capability": req.capability, "reason": reason, "by": who["id"]},
    )
    return req


async def pending_for_subject(
    session: AsyncSession, scope: TenantScope, *, subject_type: str, subject_id: str
) -> list[ApApprovalRequest]:
    return list(
        (
            await session.execute(
                select(ApApprovalRequest).where(
                    ApApprovalRequest.tenant_id == scope.tenant_id,
                    ApApprovalRequest.subject_type == subject_type,
                    ApApprovalRequest.subject_id == subject_id,
                    ApApprovalRequest.state == "pending",
                )
            )
        ).scalars().all()
    )


async def effective_approval(
    session: AsyncSession,
    scope: TenantScope,
    *,
    subject_type: str,
    subject_id: str,
    at: datetime | None = None,
) -> ApApproval | None:
    """ใบอนุมัติที่ใช้เดินงานได้ตอนนี้ — None แปลว่า **ห้ามเดิน**

    "execution ที่ไม่มี APPROVE เป็นสิ่งที่ห้าม" — ผู้เรียกต้องถือว่า None คือหยุด
    ใบที่หมดอายุแล้วใช้ไม่ได้ ต้องขอใหม่
    """
    moment = at or now()
    rows = (
        await session.execute(
            select(ApApproval)
            .where(
                ApApproval.tenant_id == scope.tenant_id,
                ApApproval.subject_type == subject_type,
                ApApproval.subject_id == subject_id,
            )
            .order_by(ApApproval.decided_at.desc())
        )
    ).scalars().all()
    if not rows:
        return None
    latest = rows[0]
    if latest.decision != "APPROVE":
        return None
    if latest.expires_at and latest.expires_at <= moment:
        return None
    return latest


async def pending_requests(
    session: AsyncSession, scope: TenantScope, *, limit: int = 50
) -> list[ApApprovalRequest]:
    return list(
        (
            await session.execute(
                select(ApApprovalRequest)
                .where(
                    ApApprovalRequest.tenant_id == scope.tenant_id,
                    ApApprovalRequest.state == "pending",
                )
                .order_by(ApApprovalRequest.requested_at)
                .limit(limit)
            )
        ).scalars().all()
    )


async def expire_overdue(session: AsyncSession, scope: TenantScope) -> int:
    """คำขอที่เลยกำหนด → `expired`

    🔒 นี่คือทางเดียวที่เวลาทำให้สถานะคำขอเปลี่ยน และมันเปลี่ยนไปทาง **หยุด** เสมอ
    ไม่มีบรรทัดไหนในไฟล์นี้ที่เวลาทำให้เกิด APPROVE
    """
    moment = now()
    rows = (
        await session.execute(
            select(ApApprovalRequest).where(
                ApApprovalRequest.tenant_id == scope.tenant_id,
                ApApprovalRequest.state == "pending",
                ApApprovalRequest.expires_at.is_not(None),
                ApApprovalRequest.expires_at <= moment,
            )
        )
    ).scalars().all()
    for req in rows:
        req.state = "expired"
        await audit.emit(
            session,
            scope,
            event_type="EXECUTION_FAILED",
            subject_type="approval",
            subject_id=req.request_id,
            transition={"from": "pending", "to": "expired"},
            error=audit.make_error(
                "approval.request.expired",
                "approval_required",
                "คำขออนุมัติหมดอายุโดยยังไม่มีคำตัดสิน — งานไม่ถูกดำเนินการ",
                retryable=True,
            ),
            attributes={"capability": req.capability, "request_id": req.request_id},
        )
    await session.flush()
    return len(rows)


def as_approval(row: ApApproval) -> dict:
    """payload ตาม `approval/v1` — ใช้ส่งออกนอกระบบและให้ payload_check validate

    🔒 `reason` ออกไปตรง ๆ ตามที่คนพิมพ์ — approval/v1 ห้ามใส่ credential/PII/private reasoning
       การกรองจึงต้องเกิดตั้งแต่ตอนรับเข้า ไม่ใช่ตอนส่งออก
    """
    payload: dict = {
        "approval_id": row.approval_id,
        "tenant_id": row.tenant_id,
        "subject": {"type": row.subject_type, "id": row.subject_id},
        "decision": row.decision,
        "reason": row.reason,
        "authority": {k: v for k, v in (row.authority or {}).items() if v},
        "decided_at": row.decided_at.isoformat(),
    }
    if row.workspace_id:
        payload["workspace_id"] = row.workspace_id
    if row.policy_id:
        payload["policy_id"] = row.policy_id
    if row.action_risk:
        payload["action_risk"] = row.action_risk
    if row.expires_at:
        payload["expires_at"] = row.expires_at.isoformat()
    return payload
