"""สัญญาณความปลอดภัย — `contracts/safety/v1`

🔒 ชื่อของทุกชนิดสัญญาณเป็น "ต้องสงสัย" ไม่ใช่ข้อสรุป — `fall_suspected` ไม่ใช่ `fall`
   เพราะสิ่งที่อุปกรณ์รู้คือค่า accelerometer ไม่ใช่ว่าผู้ป่วยล้มและบาดเจ็บ
"""

from __future__ import annotations

from datetime import datetime

from core.clock import now
from core.db import Base
from sqlalchemy import JSON, DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

EVENT_KINDS = [
    "fall_suspected",
    "left_home_unexpectedly",
    "outside_safe_area",
    "not_returned_home",
    "no_response",
    "stove_left_on",
    "door_left_open",
    "long_time_in_bathroom",
    "device_offline",
    "other",
]
SOURCE_KINDS = [
    "gps", "wearable", "door_sensor", "motion_sensor", "camera",
    "smart_appliance", "phone", "manual_report",
]
STATES = ["detected", "acknowledged", "resolved", "dismissed"]


class CareSafetyEvent(Base):
    __tablename__ = "care_safety_event"
    __table_args__ = (
        Index("ix_care_safety_dedup", "tenant_id", "patient_id", "kind", "observed_at"),
    )

    safety_event_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)

    kind: Mapped[str] = mapped_column(String(32))
    source: Mapped[dict] = mapped_column(JSON)
    # ความมั่นใจของ **อุปกรณ์** ไม่ใช่ของเรา · null = ไม่รู้ ห้ามเติมให้
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    state: Mapped[str] = mapped_column(String(16), default="detected")

    escalated: Mapped[bool] = mapped_column(default=False)
    # สัญญาณซ้ำในหน้าต่างเวลาเดียวกันถูกนับรวมที่ใบแรก ไม่สร้างใบใหม่ (กัน notification storm)
    repeat_count: Mapped[int] = mapped_column(default=1)
    acknowledged_by: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(63), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
