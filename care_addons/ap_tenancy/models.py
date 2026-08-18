"""Tenant / Workspace / Membership / Consent

🔒 โมดูลนี้ห้ามรู้จักคำว่า patient / medication / caregiver (ADR-0003 กฎข้อ 1)
   สิ่งที่ถูกคุ้มครองเรียกว่า `subject` เท่านั้น — โดเมนเป็นคน map เอง
"""

from __future__ import annotations

from datetime import datetime

from core.db import Base
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from care_addons.ap_tenancy.clock import now as _now


class ApTenant(Base):
    """ขอบเขต isolation แข็ง — ห้ามข้ามเด็ดขาด (identity/v1 · agent-platform ADR-0007)"""

    __tablename__ = "ap_tenant"

    tenant_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Bangkok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApWorkspace(Base):
    """ขอบเขตงานภายใน tenant — `Project` / `Department` เป็น label ของ workspace ไม่ใช่ชั้นใหม่"""

    __tablename__ = "ap_workspace"

    workspace_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(63), ForeignKey("ap_tenant.tenant_id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApTenantMember(Base):
    """ผูก user ของ pstack เข้ากับ tenant — user ที่ไม่ได้เป็นสมาชิก เข้าถึง tenant นั้นไม่ได้เลย"""

    __tablename__ = "ap_tenant_member"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_ap_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(63), ForeignKey("ap_tenant.tenant_id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApConsentGrant(Base):
    """ความยินยอมให้เข้าถึงข้อมูลของ subject หนึ่งราย

    consent/v1 — who · can access · which data · for what purpose · for how long
    🔒 การมีความสัมพันธ์ไม่ให้สิทธิ์อะไรโดยอัตโนมัติ ต้องมี grant เสมอ (ADR-0007)
    """

    __tablename__ = "ap_consent_grant"
    __table_args__ = (
        Index("ix_ap_consent_lookup", "tenant_id", "subject_id", "grantee_id"),
    )

    grant_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(63), ForeignKey("ap_tenant.tenant_id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[str] = mapped_column(String(63), index=True)
    grantee_type: Mapped[str] = mapped_column(String(16), default="human")
    grantee_id: Mapped[str] = mapped_column(String(63), index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    purpose: Mapped[str] = mapped_column(String(32), default="daily_care")
    granted_by_type: Mapped[str] = mapped_column(String(16), default="human")
    granted_by_id: Mapped[str] = mapped_column(String(63))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
