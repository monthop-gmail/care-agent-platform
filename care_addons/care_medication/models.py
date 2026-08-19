"""Medication version — contracts/medication/v1

🔒 append-only: ห้าม UPDATE ห้าม DELETE แถวเก่า
   เปลี่ยนได้แค่ status → superseded พร้อม superseded_by (ADR-0005)
"""

from __future__ import annotations

from datetime import datetime

from core.clock import now
from core.db import Base
from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

RELATION_TO_MEAL = [
    "before_meal",
    "with_meal",
    "after_meal",
    "empty_stomach",
    "bedtime",
    "morning",
    "as_needed",
    "specific_time",
]

INSTRUCTION_SOURCES = [
    "doctor_instruction",
    "pharmacy_label",
    "hospital_document",
    "caregiver_entry",
    "patient_entry",
]

STATUSES = ["proposed", "active", "superseded", "stopped", "needs_reconciliation"]


class CareMedicationVersion(Base):
    __tablename__ = "care_medication_version"
    __table_args__ = (
        # query "ยาวันนี้" ต้องเร็ว — index นี้อยู่ใน ADR-0005 Consequences
        Index("ix_care_med_active", "tenant_id", "patient_id", "status"),
        Index("ix_care_med_chain", "tenant_id", "medication_id", "effective_from"),
    )

    version_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    medication_id: Mapped[str] = mapped_column(String(63), index=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)

    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    route: Mapped[str] = mapped_column(String(32), default="oral")
    # [{"time": "07:00", "relation_to_meal": "before_meal", "dose": "1 tablet"}]
    schedule: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(24), default="proposed")
    instruction_source: Mapped[str] = mapped_column(String(32))
    prescribed_by: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 🔒 provenance ของคำสั่งที่มาจากข้างนอก (ADR-0010 ข้อ 7)
    #    องค์กรไหน · เอกสารใบไหน — เก็บตลอดอายุของ record เพราะเวลาโต้แย้งกันภายหลัง
    #    ต้องกลับไปดูได้ว่า "ใบนี้มาจากไหน" ไม่ใช่แค่ "ใครพิมพ์เข้าระบบ"
    source_organization_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    source_document_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    superseded_by: Mapped[str | None] = mapped_column(String(63), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
