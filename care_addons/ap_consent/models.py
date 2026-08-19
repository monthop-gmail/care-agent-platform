"""Consent grant — conform `consent/v1` ของ agent-platform (ADR-0012 ที่นั่น)

เดิมอยู่ใน `ap_tenancy` · แยกออกมาเมื่อ tenancy ขึ้น kernel เพราะ consent เป็น
**governance ไม่ใช่ infra** — ข้อสรุปเดียวกับที่เราตอบ pstack#3 และ agent-platform#15

🔒 ตารางยังชื่อ `ap_consent_grant` ตามเดิม — migration ของโมดูลนี้ **adopt ตารางที่มีอยู่แล้ว**
   ไม่สร้างใหม่ ถ้าเจอ (deployment ที่เคยรัน ap_tenancy มาก่อน)
"""

from __future__ import annotations

from datetime import datetime

from core.clock import now as _now
from core.db import Base
from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column


class ApConsentGrant(Base):
    """ความยินยอมให้เข้าถึงข้อมูลของ subject หนึ่งราย

    🔒 **ไม่มีคอลัมน์ `status`** ตาม platform_rules ของ consent/v1 — สถานะคำนวณจาก
       `revoked_at` และ `expires_at` เท่านั้น เก็บซ้ำเมื่อไรมัน drift แล้วไม่มีใครรู้ว่าอันไหนถูก
    """

    __tablename__ = "ap_consent_grant"
    __table_args__ = (
        Index("ix_ap_consent_lookup", "tenant_id", "subject_id", "grantee_id"),
    )

    grant_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    subject_id: Mapped[str] = mapped_column(String(63), index=True)
    grantee_type: Mapped[str] = mapped_column(String(16), default="human")
    grantee_id: Mapped[str] = mapped_column(String(63), index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    purpose: Mapped[str] = mapped_column(String(32), default="daily_care")
    granted_by_type: Mapped[str] = mapped_column(String(16), default="human")
    granted_by_id: Mapped[str] = mapped_column(String(63))
    # เมื่อผู้ให้ความยินยอมไม่ใช่เจ้าของข้อมูลเอง — ให้แทนโดยอำนาจอะไร
    authority_basis: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # การเพิกถอนต้องบันทึกว่าใครถอนและเพราะอะไร ด้วยมาตรฐานเดียวกับ granted_by
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    revoked_by_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
