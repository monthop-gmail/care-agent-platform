"""Appointment + preparation — contracts/appointment/v1

ระบบนี้ดูแล **กระบวนการไปพบหมอ** ไม่ใช่แค่วันเวลา
ผู้ป่วยอาจจำวันนัดได้แต่ไม่รู้ว่าต้องเตรียมอะไร — preparation จึงเป็นส่วนหนึ่งของโดเมนนี้
"""

from __future__ import annotations

from datetime import datetime

from core.clock import now
from core.db import Base
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

STATUSES = ["scheduled", "preparing", "ready", "completed", "missed", "cancelled"]

STEP_KINDS = [
    "instructions_acknowledged",
    "documents_ready",
    "clothes_ready",
    "medication_ready",
    "fasting_requirement",
    "transport_ready",
    "ready_to_leave",
]

STEP_STATUSES = ["pending", "done", "skipped", "needs_help"]

# ขั้นที่เป็นข้อกำหนดทางการแพทย์ — ต้องมีเอกสารอ้างอิงเสมอ ห้ามให้ระบบคิดเอง
STEPS_REQUIRING_SOURCE = {"fasting_requirement"}


class CareAppointment(Base):
    __tablename__ = "care_appointment"
    __table_args__ = (Index("ix_care_appt_patient", "tenant_id", "patient_id", "starts_at"),)

    appointment_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    doctor_name: Mapped[str] = mapped_column(String(255), default="")
    specialty: Mapped[str | None] = mapped_column(String(64), nullable=True)
    facility: Mapped[str] = mapped_column(String(255), default="")
    purpose: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    reminder_offsets_hours: Mapped[list] = mapped_column(JSON, default=lambda: [24, 2])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CarePreparationStep(Base):
    """หนึ่งขั้นของการเตรียมตัว — เป็น state จริง ไม่ใช่ checklist ในหัวผู้ป่วย

    เพราะผู้ป่วยอาจตอบว่า "ครับ" แต่จริง ๆ ยังไม่ได้ทำ ระบบจึงต้องรู้ว่าค้างอยู่ขั้นไหน
    """

    __tablename__ = "care_preparation_step"
    __table_args__ = (Index("ix_care_prep_appt", "tenant_id", "appointment_id", "due_at"),)

    step_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    appointment_id: Mapped[str] = mapped_column(
        String(63), ForeignKey("care_appointment.appointment_id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(255))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    order: Mapped[int] = mapped_column(Integer, default=0)
    # 🔒 บังคับสำหรับ fasting_requirement — อ้างเอกสารของสถานพยาบาลเท่านั้น
    source_document: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
