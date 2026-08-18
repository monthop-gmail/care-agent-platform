"""Audit event — append-only

🔒 guarantee ที่ลดทอนไม่ได้ (agent-platform event/v1):
   - event เป็น append-only แก้หรือลบไม่ได้
   - no silent state change — ทุกการเปลี่ยน state ต้องมี event
   - event ที่ resolve tenant ไม่ได้ ให้ reject ที่ intake ห้ามเดา tenant ให้
   - external event ต้องคง source ไว้ให้รู้ตลอดไปว่ามาจากข้างนอก
   - ห้ามเก็บ private reasoning / chain-of-thought เป็น audit record

🔒 โมดูลนี้ห้ามรู้จักคำว่า patient / medication / caregiver (ADR-0003 กฎข้อ 1)
   โดเมนใส่ข้อมูลของตัวเองใน `attributes`
"""

from __future__ import annotations

from datetime import datetime

from core.db import Base
from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class ApAuditEvent(Base):
    __tablename__ = "ap_audit_event"
    __table_args__ = (
        Index("ix_ap_audit_tenant_time", "tenant_id", "occurred_at"),
        Index("ix_ap_audit_subject", "tenant_id", "subject_type", "subject_id"),
        Index("ix_ap_audit_correlation", "correlation_id"),
    )

    event_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    care_event_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(63), nullable=True)

    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(63))
    job_id: Mapped[str | None] = mapped_column(String(63), nullable=True, index=True)
    execution_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(63), nullable=True)

    actor: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_kind: Mapped[str] = mapped_column(String(16), default="internal")
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)

    transition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    policy_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
