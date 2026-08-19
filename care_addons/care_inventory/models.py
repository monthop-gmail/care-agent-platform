"""ของที่บ้าน — `contracts/inventory/v1`

🔒 ไม่มีคอลัมน์ `expired` โดยเจตนา — คำนวณจาก `expires_on` เทียบวันนี้เท่านั้น
   (เหตุผลเดียวกับที่ consent/v1 ห้ามเก็บ status ซ้ำกับ revoked_at:
    สถานะที่เก็บซ้ำจะเพี้ยนจากความจริงในวันที่ไม่มีใครไปอัปเดตมัน)
"""

from __future__ import annotations

from datetime import date, datetime

from core.clock import now
from core.db import Base
from sqlalchemy import JSON, Date, DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

CATEGORIES = ["food", "drink", "medicine_supply", "hygiene", "cleaning", "household", "other"]
STATUSES = ["in_stock", "consumed", "discarded"]


class CareInventoryItem(Base):
    __tablename__ = "care_inventory_item"
    __table_args__ = (
        Index("ix_care_inventory_lookup", "tenant_id", "patient_id", "normalized_name", "status"),
    )

    item_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)

    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(24))
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str] = mapped_column(String(32), default="")
    # ที่อยู่จริงในบ้าน ("ตู้เย็นชั้นบน") ไม่ใช่หมวดหมู่ — ผู้ป่วยต้องเดินไปหยิบได้จากคำตอบนี้
    location: Mapped[str] = mapped_column(String(255), default="")

    # null = ไม่มีวันหมดอายุ **หรือยังไม่รู้** — ทั้งสองอย่างห้ามเดาให้ (inventory_rules ข้อ 1)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    opened_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="in_stock")

    recorded_by: Mapped[dict] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
