"""Care job + notification — contracts/escalation/v1

หลักการ: reminder ที่ไม่มี job = ข้อความลอย ห้ามมีในระบบนี้
"""

from __future__ import annotations

from datetime import datetime

from core.db import Base
from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from care_addons.ap_tenancy.clock import now

JOB_STATES = ["pending", "reminded", "acknowledged", "confirmed", "missed", "escalated", "cancelled"]


class CareJob(Base):
    __tablename__ = "care_job"
    __table_args__ = (
        Index("ix_care_job_due", "tenant_id", "state", "next_attempt_at"),
        Index("ix_care_job_patient", "tenant_id", "patient_id", "due_at"),
        Index("ix_care_job_source", "tenant_id", "source_kind", "source_id", "due_at"),
    )

    care_job_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    source_kind: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[str] = mapped_column(String(63))
    label: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(16), default="pending")
    severity: Mapped[str] = mapped_column(String(16), default="medium")

    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    correlation_id: Mapped[str] = mapped_column(String(63), index=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CareNotification(Base):
    """ข้อความที่ส่งออกจริง — เก็บไว้ให้ตรวจสอบย้อนหลังได้ว่าใครได้รับอะไรเมื่อไร"""

    __tablename__ = "care_notification"
    __table_args__ = (
        Index("ix_care_notif_lookup", "tenant_id", "patient_id", "audience", "sent_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    audience: Mapped[str] = mapped_column(String(16))  # patient | caregiver
    target_principal_id: Mapped[str] = mapped_column(String(63))
    channel: Mapped[str] = mapped_column(String(16), default="app")
    text: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), default="low")
    care_job_id: Mapped[str | None] = mapped_column(String(63), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    aggregated_count: Mapped[int] = mapped_column(Integer, default=1)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
