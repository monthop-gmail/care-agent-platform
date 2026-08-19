"""คำขออนุมัติ + คำตัดสิน — conform `approval/v1` ของ agent-platform

**approval ≠ policy** — `policy/v1` ตอบว่า *"ต้องขออนุมัติไหม"* · ที่นี่คือ *คำตัดสินของผู้มีอำนาจ*

🔒 guarantee ที่ลดทอนไม่ได้ (approval/v1):
   - decision เป็น **immutable** — เปลี่ยนใจ = ออกใบใหม่ที่อ้างใบเดิม (`supersedes`)
   - ทุก APPROVE ต้องมี event GOVERNANCE_DECISION คู่กันเสมอ
   - execution ที่ไม่มี APPROVE เป็นสิ่งที่ห้าม
   - REQUIRE_CHANGES ไม่ใช่ REJECT — งานยังมีชีวิตและกลับมายื่นใหม่ได้

🔒 โมดูลนี้ห้ามรู้จักคำของโดเมน (ADR-0003 กฎ 1) — สิ่งที่ขออนุมัติเรียกว่า `subject`
"""

from __future__ import annotations

from datetime import datetime

from core.clock import now as _now
from core.db import Base
from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

# ชุดปิดของ approval/v1 — เพิ่มค่าใหม่ = semantic change ต้องมี RFC ที่ devfactory-core ก่อน
DECISIONS = ["APPROVE", "REJECT", "REQUIRE_CHANGES"]

REQUEST_STATES = ["pending", "approved", "rejected", "changes_requested", "expired", "withdrawn"]

# ชนิดของ subject ตาม approval/v1 $.subject.type
SUBJECT_TYPES = ["job", "execution", "tool_call", "artifact", "deployment"]


class ApApprovalRequest(Base):
    """คำขอ — 🔒 **ไม่มี auto-approve** ไม่ว่ารอนานแค่ไหน

    คำขอที่เลยกำหนดจะกลายเป็น `expired` (งานไม่เดิน) ไม่ใช่ `approved`
    — timeout ทำให้ระบบหยุด ไม่ใช่ทำให้ระบบลงมือ
    """

    __tablename__ = "ap_approval_request"
    __table_args__ = (Index("ix_ap_approval_pending", "tenant_id", "state", "expires_at"),)

    request_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(63), nullable=True)

    capability: Mapped[str] = mapped_column(String(64), index=True)
    action_risk: Mapped[str] = mapped_column(String(16))
    # authority ที่ policy บอกว่าต้องมี — approval_required หรือ human_command_required
    authority_required: Mapped[str] = mapped_column(String(32))
    policy_id: Mapped[str] = mapped_column(String(64))

    subject_type: Mapped[str] = mapped_column(String(24))
    subject_id: Mapped[str] = mapped_column(String(63), index=True)
    summary: Mapped[str] = mapped_column(Text)
    # สิ่งที่จะเกิดขึ้นถ้าอนุมัติ — เก็บไว้ให้ผู้ตัดสินเห็นว่ากำลังอนุมัติอะไร
    proposed: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    requested_by: Mapped[dict] = mapped_column(JSON)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="pending")
    correlation_id: Mapped[str | None] = mapped_column(String(63), nullable=True)


class ApApproval(Base):
    """คำตัดสิน — 🔒 immutable หลังบันทึก · เปลี่ยนใจ = ใบใหม่ที่ `supersedes` ใบเดิม"""

    __tablename__ = "ap_approval"
    __table_args__ = (Index("ix_ap_approval_subject", "tenant_id", "subject_type", "subject_id"),)

    approval_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    request_id: Mapped[str] = mapped_column(
        String(63), ForeignKey("ap_approval_request.request_id", ondelete="CASCADE"), index=True
    )

    subject_type: Mapped[str] = mapped_column(String(24))
    subject_id: Mapped[str] = mapped_column(String(63))
    decision: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text)
    authority: Mapped[dict] = mapped_column(JSON)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes: Mapped[str | None] = mapped_column(String(63), nullable=True)
