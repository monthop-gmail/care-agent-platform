"""บันทึกสรุปประจำวัน — หนึ่งผู้ป่วย หนึ่งวันตามเวลาท้องถิ่นของผู้ป่วย หนึ่งแถว

ที่ต้องเก็บลงตารางไม่ใช่คำนวณสด ๆ ทุกครั้ง เพราะ:
  1. ต้องส่ง **วันละครั้ง** — worker วนทุก 15 นาที ต้องรู้ได้ว่าวันนี้ส่งไปแล้ว
  2. ผู้ดูแลต้องเปิดย้อนดูของเมื่อวานได้ว่าตอนนั้นระบบเห็นอะไร ไม่ใช่เห็นตัวเลขที่คำนวณใหม่วันนี้
"""

from __future__ import annotations

from datetime import date, datetime

from core.clock import now as _now
from core.db import Base
from sqlalchemy import JSON, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class CareDailySummary(Base):
    __tablename__ = "care_daily_summary"
    __table_args__ = (
        # 🔒 กันส่งซ้ำระดับ DB ไม่ใช่แค่ระดับโค้ด — worker อาจรันซ้อนกันได้
        UniqueConstraint("tenant_id", "patient_id", "local_date", name="uq_care_daily_summary_day"),
    )

    summary_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    local_date: Mapped[date] = mapped_column(Date)

    facts: Mapped[dict] = mapped_column(JSON)
    text: Mapped[str] = mapped_column(String(4000))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recipients: Mapped[int] = mapped_column(Integer, default=0)
