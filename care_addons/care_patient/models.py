"""Patient / Caregiver / Care team — contracts/patient/v1"""

from __future__ import annotations

from datetime import datetime

from core.db import Base
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from care_addons.ap_tenancy.clock import now

# 🔒 default ของทุกความสามารถคือปิด — ต้องเลือกเปิดเอง ไม่มีการเปิดอัตโนมัติจากข้อมูลสุขภาพ
DEFAULT_CARE_PROFILE = {
    "routine": False,
    "medication": False,
    "appointment": False,
    "nutrition": False,
    "safety": False,
    "memory_assistance": False,
    "daily_living": False,
    "caregiver_escalation": False,
}


class CarePatient(Base):
    __tablename__ = "care_patient"
    __table_args__ = (Index("ix_care_patient_tenant", "tenant_id", "status"),)

    patient_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255))
    # 🔒 routine/appointment ทุกอย่างตีความด้วย timezone นี้ ห้ามใช้ค่าของ server
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Bangkok")
    care_profile: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_CARE_PROFILE))
    channels: Mapped[list] = mapped_column(JSON, default=lambda: ["app"])
    # ชั้น PLACE ของ orientation — "ตอนนี้อยู่ที่ไหน" ต้องตอบจากค่าที่คนตั้งไว้ ไม่ใช่เดาจาก IP/GPS
    home_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quiet_hours_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    quiet_hours_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # 🔒 ห้ามเพิ่มคอลัมน์ที่เก็บการวินิจฉัยโรคที่นี่ (patient_rules · ADR-0006)


class CareCaregiver(Base):
    __tablename__ = "care_caregiver"

    caregiver_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    principal_id: Mapped[str] = mapped_column(String(63), index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    relation: Mapped[str] = mapped_column(String(64), default="")
    channel: Mapped[str] = mapped_column(String(16), default="app")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CareTeamMember(Base):
    """ผูก caregiver กับผู้ป่วย + ลำดับการ escalate

    🔒 การอยู่ในทีมดูแล **ไม่ให้สิทธิ์เข้าถึงข้อมูล** — สิทธิ์มาจาก consent เท่านั้น (ADR-0007)
    """

    __tablename__ = "care_team_member"
    __table_args__ = (Index("ix_care_team_patient", "tenant_id", "patient_id", "escalation_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(
        String(63), ForeignKey("care_patient.patient_id", ondelete="CASCADE"), index=True
    )
    caregiver_id: Mapped[str] = mapped_column(
        String(63), ForeignKey("care_caregiver.caregiver_id", ondelete="CASCADE")
    )
    escalation_order: Mapped[int] = mapped_column(Integer, default=1)
    is_emergency_contact: Mapped[bool] = mapped_column(Boolean, default=False)
