"""องค์กรภายนอกและสมาชิก — `contracts/organization/v1`

🔒 tenant-scoped โดยตั้งใจ (ADR-0010 ข้อ 2) — นี่คือ "โรงพยาบาลที่บ้านนี้ไป"
   ไม่ใช่ทะเบียนกลางของทั้งระบบ · ทะเบียนกลางจะเปิดช่องให้ครอบครัวหนึ่ง
   รู้ว่าครอบครัวอื่นไปหาหมอที่ไหน ซึ่งเป็นข้อมูลอ่อนไหวของผู้ป่วย
"""

from __future__ import annotations

from datetime import date, datetime

from core.clock import now
from core.db import Base
from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

ORG_KINDS = ["clinic", "hospital", "pharmacy", "nursing_home", "home_care", "laboratory", "other"]
MEMBER_ROLES = ["doctor", "nurse", "pharmacist", "therapist", "coordinator", "other"]


class CareOrganization(Base):
    __tablename__ = "care_organization"
    __table_args__ = (Index("ix_care_organization_lookup", "tenant_id", "kind"),)

    organization_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(24))
    # รหัสในระบบต้นทาง — ว่างได้ ใช้ตอนเชื่อมระบบจริงเพื่อจับคู่โดยไม่ต้องเดาจากชื่อ
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_by: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CareOrgMembership(Base):
    """ใครทำงานอยู่ที่องค์กรไหน — 🔒 เป็น **เงื่อนไขของสิทธิ์** ไม่ใช่ข้อมูลประกอบ

    หมอที่ลาออกแล้วต้องเข้าไม่ได้ทันที แม้ใบ consent จะยังไม่หมดอายุ (ADR-0010 ข้อ 4)
    """

    __tablename__ = "care_org_membership"
    __table_args__ = (
        Index("ix_care_org_membership_principal", "tenant_id", "principal_id", "active"),
    )

    membership_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    organization_id: Mapped[str] = mapped_column(
        String(63),
        ForeignKey("care_organization.organization_id", ondelete="CASCADE"),
        index=True,
    )
    principal_type: Mapped[str] = mapped_column(String(16), default="human")
    principal_id: Mapped[str] = mapped_column(String(63), index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(24), default="doctor")

    # 🔒 ไม่ลบแถวทิ้งเมื่อคนออก — audit ต้องตอบได้ว่าใครเคยเข้าถึงได้ในช่วงไหน
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ended_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
