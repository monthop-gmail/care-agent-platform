"""ของใช้ประจำตัว — `contracts/home/v1`

    "กุญแจอยู่ไหน" · "ชุดนี้ใส่แล้วหรือยัง" · "พรุ่งนี้ใส่ชุดไหน"

🔒 `unknown` เป็นค่าที่ถูกต้อง ไม่ใช่ข้อมูลขาด — "จำไม่ได้" คือคำตอบจริงที่ระบบต้องรับได้
   และต้องนำไปสู่ workflow ที่ปลอดภัย ไม่ใช่การเดาแทนผู้ป่วย
"""

from __future__ import annotations

from datetime import date, datetime

from core.db import Base
from sqlalchemy import JSON, Date, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from care_addons.ap_tenancy.clock import now

ITEM_KINDS = [
    "clothing", "keys", "wallet", "glasses", "phone", "document", "hearing_aid", "cane", "other",
]
ITEM_STATES = ["ready", "used", "in_laundry", "unknown", "lost"]


class CareHomeItem(Base):
    __tablename__ = "care_home_item"
    __table_args__ = (Index("ix_care_home_lookup", "tenant_id", "patient_id", "kind", "state"),)

    item_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)

    kind: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(16), default="unknown")
    # ที่อยู่ประจำที่ตกลงกันไว้ — "ตะกร้าข้างประตู" ไม่ใช่พิกัด GPS
    # นี่คือ cognitive offloading จริง ๆ: ของอยู่ที่เดิมเสมอ ผู้ป่วยจึงไม่ต้องจำ
    home_location: Mapped[str] = mapped_column(String(255), default="")

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_confirmed_by: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    set_aside_for: Mapped[date | None] = mapped_column(Date, nullable=True)
    set_aside_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
