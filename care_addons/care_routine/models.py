"""Routine item — contracts/routine/v1"""

from __future__ import annotations

from datetime import datetime

from core.db import Base
from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from care_addons.ap_tenancy.clock import now

KINDS = ["wake", "meal", "medication", "activity", "hygiene", "rest", "sleep", "hydration", "custom"]


class CareRoutineItem(Base):
    __tablename__ = "care_routine_item"
    __table_args__ = (Index("ix_care_routine_patient", "tenant_id", "patient_id", "enabled"),)

    routine_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(255))
    # เวลาตาม timezone ของผู้ป่วย ไม่ใช่ของ server (routine_rules)
    scheduled_time: Mapped[str] = mapped_column(String(5))
    recurrence_type: Mapped[str] = mapped_column(String(16), default="daily")
    days_of_week: Mapped[list | None] = mapped_column(JSON, nullable=True)
    grace_minutes: Mapped[int] = mapped_column(Integer, default=30)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
