"""Care job + notification — contracts/escalation/v1

หลักการ: reminder ที่ไม่มี job = ข้อความลอย ห้ามมีในระบบนี้
"""

from __future__ import annotations

from datetime import datetime

from core.clock import now
from core.db import Base
from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

JOB_STATES = ["pending", "reminded", "acknowledged", "confirmed", "missed", "escalated", "cancelled"]


class CareJob(Base):
    __tablename__ = "care_job"
    __table_args__ = (
        Index("ix_care_job_due", "tenant_id", "state", "next_attempt_at"),
        Index("ix_care_job_patient", "tenant_id", "patient_id", "due_at"),
        Index("ix_care_job_source", "tenant_id", "source_kind", "source_id", "due_at"),
    )

    care_job_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    source_kind: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[str] = mapped_column(String(63))
    label: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(16), default="pending")
    severity: Mapped[str] = mapped_column(String(16), default="medium")

    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    correlation_id: Mapped[str] = mapped_column(String(63), index=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── presentation intent (ADR-0014) ────────────────────────────────────────────
#
# 🔒 ทุกค่าเป็น **code จาก vocabulary ปิด** ไม่ใช่ข้อความเสรี — เพราะ intent เป็นของที่
#    ต้องตรวจย้อนได้ และ audit เก็บตัวชี้ ไม่ใช่เนื้อหา (ADR-0011)
#
# 🔒 `dwell` เป็น code ไม่ใช่วินาที โดยเจตนา — "30 วินาที" บนจอ 55 นิ้วกับบนแท็บเล็ต
#    ไม่ใช่ประสบการณ์เดียวกัน การแปลงเป็นเวลาจริงเป็นงานของ endpoint
PRESENTATION = {
    "surface": ["overlay", "full_screen", "ambient"],
    "speak": [True, False],
    "response": ["required", "optional", "none"],
    "dwell": ["short", "medium", "until_answered"],
}


def validated_presentation(intent: dict | None) -> dict | None:
    """intent ที่ผิดรูปต้องพังตอนสร้าง ไม่ใช่ตอนแสดง"""
    if not intent:
        return None
    unknown = set(intent) - set(PRESENTATION)
    if unknown:
        raise ValueError(
            f"presentation ไม่รู้จักคีย์ {sorted(unknown)} — ต้องเป็น {sorted(PRESENTATION)}"
        )
    for key, value in intent.items():
        if value not in PRESENTATION[key]:
            raise ValueError(
                f"presentation.{key}={value!r} ไม่อยู่ในชุดปิด {PRESENTATION[key]}"
            )
    return dict(intent)


class CareNotification(Base):
    """ข้อความที่ส่งออกจริง — เก็บไว้ให้ตรวจสอบย้อนหลังได้ว่าใครได้รับอะไรเมื่อไร"""

    __tablename__ = "care_notification"
    __table_args__ = (
        Index("ix_care_notif_lookup", "tenant_id", "patient_id", "audience", "sent_at"),
        Index("ix_care_notif_stream", "tenant_id", "stream", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(63), index=True)
    patient_id: Mapped[str] = mapped_column(String(63), index=True)
    audience: Mapped[str] = mapped_column(String(16))  # patient | caregiver
    target_principal_id: Mapped[str] = mapped_column(String(63))
    channel: Mapped[str] = mapped_column(String(16), default="app")
    text: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), default="low")
    care_job_id: Mapped[str | None] = mapped_column(String(63), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    aggregated_count: Mapped[int] = mapped_column(Integer, default=1)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # ส่งออกจริงหรือยัง — "บันทึกว่าส่ง" กับ "ส่งถึงจริง" เป็นคนละเรื่อง
    # ข้อความที่ส่งไม่ออกต้องเห็นได้ ไม่ใช่หายเงียบ
    delivery_status: Mapped[str] = mapped_column(String(16), default="pending")
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── presentation (ADR-0014) ──
    #
    # 🔒 `presentation` คือ **คำขอ** ไม่ใช่สิ่งที่ได้ — `effective_presentation()` เป็นผู้ตัดสิน
    #    หลังผ่าน severity กับ quiet hours · เก็บคำขอไว้เพื่อให้ตรวจย้อนได้ว่าขออะไรไป
    presentation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # ── กำหนดตาย (ADR-0016) ──
    #
    # 🔒 โดเมนตั้ง อุปกรณ์บังคับตาม · `expires_at = None` ต้องมาจากกฎที่ประกาศเหตุผลไว้
    #    (`care_endpoint.expiry` ชนิด `caregiver_help`) ไม่ใช่จากการหาค่าไม่เจอ
    #    `expiry_class` เป็น code จากทะเบียนปิด จึงใส่ใน audit/metrics ได้ ไม่มี PII
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 🔒 สายงานของการแสดงผล — ใบใหม่ในสายเดียวกัน **แทน** ใบเก่า ไม่ใช่เพิ่มจากใบเก่า
    #    โดเมนเป็นคนประกาศว่าอะไรแทนอะไรได้ · `None` = ใบนี้ไม่มีใครแทนได้
    stream: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 🔒 endpoint รายงานว่าวางบนจอจริงแล้ว — อยู่ข้าง delivery ไม่ใช่ข้าง evidence
    #    "แสดงบนจอแล้ว" ไม่ใช่หลักฐานว่าคนเห็น และไม่มีทางกลายเป็น evidence (ADR-0014 ข้อ 5)
    presented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
