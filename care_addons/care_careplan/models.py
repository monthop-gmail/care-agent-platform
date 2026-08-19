"""Care plan task — `contracts/careplan/v1`

🔒 มาจาก **คำสั่งของผู้มีอำนาจ** เท่านั้น — ระบบไม่คิด care plan เอง (ADR-0006)
   ไม่มี field ไหนในตารางนี้ที่ให้ระบบ "ออกแบบ" อะไรให้ผู้ป่วย มีแต่ที่จดว่าใครสั่งอะไรมา
"""

from __future__ import annotations

from datetime import date, datetime

from core.db import Base
from sqlalchemy import JSON, Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from care_addons.ap_tenancy.clock import now

TASK_TYPES = [
    "exercise", "hydration", "topical_treatment", "wound_care",
    "diet", "sleep", "follow_up", "restriction", "other",
]
FREQUENCY_TYPES = ["daily", "times_per_day", "weekly", "once", "ongoing"]
SOURCE_KINDS = ["doctor_visit", "hospital_document", "caregiver_entry"]
STATUSES = ["proposed", "active", "paused", "completed", "cancelled"]

# 🔒 คำสั่งที่เป็น "ข้อห้าม" ไม่ใช่ "งานที่ต้องทำ" — เตือนเป็นเวลาไม่ได้
#    "งดอาหารเค็ม" ไม่มีเวลาให้ทำเสร็จ การส่ง reminder ทุกวันจึงเป็นเสียงรบกวน ไม่ใช่การดูแล
STANDING_INSTRUCTION_TYPES = {"restriction", "diet"}


class CareCarePlanTask(Base):
    __tablename__ = "care_careplan_task"
    __table_args__ = (
        Index("ix_care_careplan_patient", "tenant_id", "patient_id", "status"),
    )

    task_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)

    task_type: Mapped[str] = mapped_column(String(24))
    description: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frequency: Mapped[dict] = mapped_column(JSON)
    # ส่วนขยายของเรา ไม่ได้อยู่ใน careplan/v1: เวลาที่จะเตือนจริงตาม timezone ของผู้ป่วย
    # contract บอกแค่ "บ่อยแค่ไหน" — การจะเตือนตอนไหนเป็นเรื่องของครอบครัว ไม่ใช่ของหมอ
    scheduled_times: Mapped[list] = mapped_column(JSON, default=list)

    source: Mapped[dict] = mapped_column(JSON)
    start_date: Mapped[date] = mapped_column(Date)
    # null = ทำต่อเนื่องจนกว่าจะทบทวนกันในนัดครั้งหน้า (careplan/v1)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    severity: Mapped[str] = mapped_column(String(16), default="medium")

    activated_by: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at_appointment_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_by: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # เก็บถ้อยคำต้นทางไว้เสมอ — เวลาโต้แย้งกันภายหลังต้องกลับไปดูได้ว่าหมอสั่งว่าอะไร
    source_document: Mapped[str | None] = mapped_column(Text, nullable=True)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
