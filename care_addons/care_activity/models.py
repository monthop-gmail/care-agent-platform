"""งานหลายขั้นตอน — `contracts/activity/v1`

    เปิดเครื่องซักผ้า → เครื่องเสร็จ → เอาผ้าออก → ตาก

ผู้ป่วยความจำถดถอย "เริ่มได้" แต่มักไม่จบ — ผ้าค้างในเครื่องข้ามคืนคือปัญหาจริง
🔒 เครื่องซักเสร็จ **ไม่ใช่** งานเสร็จ (activity_rules ข้อ 1)
"""

from __future__ import annotations

from datetime import datetime

from core.db import Base
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from care_addons.ap_tenancy.clock import now

ACTIVITY_TYPES = [
    "laundry", "cooking", "cleaning", "bathing", "appointment_prep", "exercise", "custom",
]

# escalation/v1 $defs.TaskState
TASK_STATES = [
    "not_started", "starting", "in_progress", "waiting", "blocked",
    "ready_for_next_step", "completed", "abandoned", "needs_help",
]

CONTEXT_CHECKS = ["weather", "time_of_day", "machine_status", "existing_tasks", "care_plan"]


class CareActivity(Base):
    __tablename__ = "care_activity"
    __table_args__ = (Index("ix_care_activity_open", "tenant_id", "patient_id", "state"),)

    activity_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    activity_type: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(24), default="not_started")
    # 🔒 ข้อมูลประกอบเท่านั้น — เสนอได้ ห้ามใช้ห้ามผู้ป่วยทำ (activity_rules ข้อ 4)
    context_checks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(63), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CareActivityStep(Base):
    __tablename__ = "care_activity_step"
    __table_args__ = (Index("ix_care_activity_step_order", "tenant_id", "activity_id", "order"),)

    step_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    activity_id: Mapped[str] = mapped_column(
        String(63), ForeignKey("care_activity.activity_id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(255))
    order: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(24), default="not_started")
    # ขั้นที่ต้องรอสัญญาณจากข้างนอก (เครื่องซักเสร็จ) — ไม่มี integration ให้ถามผู้ป่วยแทน
    # 🔒 ห้ามเดาว่าเสร็จแล้ว
    awaits_external_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stalled_after_minutes: Mapped[int] = mapped_column(Integer, default=60)
    care_job_id: Mapped[str | None] = mapped_column(String(63), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stalled_reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
