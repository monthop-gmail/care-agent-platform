"""Health journal entry — contracts/journal/v1"""

from __future__ import annotations

from datetime import datetime

from core.clock import now
from core.db import Base
from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

ENTRY_TYPES = ["observation", "question", "concern", "side_effect", "event"]
CLASSIFICATIONS = ["unclassified", "possibly_relevant", "patient_assigned", "caregiver_assigned"]


class CareJournalEntry(Base):
    __tablename__ = "care_journal_entry"
    __table_args__ = (Index("ix_care_journal_patient", "tenant_id", "patient_id", "status"),)

    entry_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    entry_type: Mapped[str] = mapped_column(String(16))
    # 🔒 คำพูดต้นฉบับของผู้ป่วย — ห้าม LLM เขียนทับ (journal_rules)
    text: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    recorded_by: Mapped[dict] = mapped_column(JSON)
    classification: Mapped[str] = mapped_column(String(24), default="unclassified")
    target_specialty: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="open")
    answer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
