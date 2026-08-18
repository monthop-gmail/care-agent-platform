"""ผูกบัญชี LINE เข้ากับผู้ป่วย/ผู้ดูแล

pstack มี `line_users.user_id` สำหรับผูกกับ **pstack user** อยู่แล้ว แต่ผู้ป่วยส่วนใหญ่
ไม่ได้เป็น user ของระบบ (ไม่มี email ไม่มีรหัสผ่าน และไม่ควรต้องมี) โมดูลนี้จึงผูก
LINE user เข้ากับ **principal ของโดเมน care** โดยตรง ภายใต้ tenant ที่ระบุชัด
"""

from __future__ import annotations

from datetime import datetime

from core.db import Base
from sqlalchemy import Boolean, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from care_addons.ap_tenancy.clock import now

ROLES = ["patient", "caregiver"]


class CareLineBinding(Base):
    """LINE user หนึ่งคน = principal หนึ่งตัวใน tenant หนึ่ง"""

    __tablename__ = "care_line_binding"
    __table_args__ = (
        UniqueConstraint("channel_id", "line_user_id", name="uq_care_line_binding"),
        Index("ix_care_line_principal", "tenant_id", "principal_id"),
    )

    binding_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    channel_id: Mapped[str] = mapped_column(String(64), index=True)
    line_user_id: Mapped[str] = mapped_column(String(64), index=True)
    principal_id: Mapped[str] = mapped_column(String(63), index=True)
    role: Mapped[str] = mapped_column(String(16))
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CareLinePairingCode(Base):
    """โค้ดจับคู่ — ผู้ดูแลสร้างให้ แล้วพิมพ์ในแชท LINE

    🔒 ใช้ได้ครั้งเดียวและมีวันหมดอายุ — เพราะใครก็ตามที่ถือโค้ดนี้จะเข้าถึงข้อมูลผู้ป่วยได้
    """

    __tablename__ = "care_line_pairing_code"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    principal_id: Mapped[str] = mapped_column(String(63))
    role: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[str] = mapped_column(String(63))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
