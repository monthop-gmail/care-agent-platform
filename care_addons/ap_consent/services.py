"""ความยินยอมเข้าถึงข้อมูลของบุคคล — conform `consent/v1` ของ agent-platform

ย้ายมาจาก `ap_tenancy` ตอน tenancy ขึ้น kernel · primitives ของ tenant มาจาก `core.tenancy`

สองด่านเสมอ (ADR-0007):
    RBAC ของ pstack (ทำ action นี้ได้ไหม) → consent ที่นี่ (กับ subject รายนี้ ตอนนี้ ได้ไหม)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from core.clock import now
from core.tenancy import Principal, TenantScope, assert_same_tenant, new_id, scoped, validate_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_consent.models import ApConsentGrant

logger = logging.getLogger(__name__)

# consent/v1 $defs.Condition — schema บังคับแค่รูปของชื่อ ไม่ใช่รายการค่า (ชุดเปิด)
CONDITION_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

# ที่เก็บผลการประเมินล่าสุดใน session — `ap_audit` อ่านคีย์นี้เพื่อแนบลง event ถัดไป
#
# 🔒 ใช้ session.info แทนการ import ข้ามโมดูล เพราะ `ap_audit` เป็นชั้นล่างของ `ap_consent`
#    (consent depends audit) การให้ audit import consent จะเป็นวงกลม
#    · คีย์นี้เป็นสัญญาระหว่างสองโมดูล เปลี่ยนต้องแก้ทั้งคู่พร้อมกัน
EVALUATION_KEY = "ap_consent.evaluation"


class ConsentDenied(PermissionError):
    pass


async def grant_consent(
    session: AsyncSession,
    scope: TenantScope,
    *,
    subject_id: str,
    grantee: Principal,
    scopes: list[str],
    purpose: str = "daily_care",
    granted_by: Principal,
    authority_basis: str | None = None,
    expires_at: datetime | None = None,
    conditions: list[dict] | None = None,
) -> ApConsentGrant:
    """สร้างความยินยอมหนึ่งใบ — conform `consent/v1`

    `authority_basis` บังคับเมื่อผู้ให้ความยินยอมไม่ใช่เจ้าของข้อมูลเอง
    (contract บอกว่า optional แต่เราบังคับ เพราะโดเมนนี้ผู้ให้แทนคือกรณีปกติ
    ไม่ใช่ข้อยกเว้น — ถ้าไม่บันทึก audit จะตอบไม่ได้ว่าทำไมคนนั้นให้แทนได้)
    """
    if not scopes:
        raise ValueError("consent ต้องระบุ scope อย่างน้อยหนึ่งอย่าง — grant ที่ไม่มี scope ไม่มีความหมาย")
    if not purpose:
        raise ValueError("consent ต้องระบุ purpose — ความยินยอมที่ไม่บอกวัตถุประสงค์ตอบ audit ไม่ได้")
    for condition in conditions or []:
        kind = (condition or {}).get("kind")
        if not isinstance(kind, str) or not CONDITION_KIND_PATTERN.match(kind):
            raise ValueError(
                f"condition.kind ไม่ตรงรูปของ consent/v1: {kind!r} "
                f"(ต้องเป็น ^[a-z][a-z0-9_]{{2,63}}$)"
            )
        # 🔒 consent/v1 ปิด additionalProperties ที่ตัวเงื่อนไข — คำของโดเมนต้องอยู่ใน params
        #    ไม่งั้น key ที่พิมพ์ผิดจะ valid เงียบ ๆ แล้วเงื่อนไขจะไม่ถูกตรวจอย่างที่ตั้งใจ
        extra = set(condition) - {"kind", "params"}
        if extra:
            raise ValueError(
                f"condition มี key นอก {{kind, params}}: {sorted(extra)} "
                f"— ค่าของโดเมนต้องอยู่ในกล่อง params (consent/v1 v1.1.0)"
            )
        if condition_checker(kind) is None:
            raise ValueError(
                f"เงื่อนไข '{kind}' ไม่มีตัวตรวจที่ลงทะเบียนไว้ — ใบที่ตรวจเงื่อนไขไม่ได้ "
                f"จะใช้ไม่ได้เลยตอน runtime ดังนั้นห้ามออกใบตั้งแต่แรก"
            )
    if granted_by.id != subject_id and not authority_basis:
        raise ValueError(
            f"{granted_by.id} ให้ความยินยอมแทน {subject_id} จึงต้องระบุ authority_basis "
            f"ว่าให้แทนโดยอำนาจอะไร (ผู้อนุบาล · หนังสือมอบอำนาจ · ผู้ปกครองตามกฎหมาย)"
        )
    grant = ApConsentGrant(
        grant_id=new_id("grant"),
        tenant_id=scope.tenant_id,
        subject_id=validate_id(subject_id, "subject_id"),
        grantee_type=grantee.type,
        grantee_id=grantee.id,
        scopes=list(scopes),
        conditions=list(conditions) if conditions else None,
        purpose=purpose,
        granted_by_type=granted_by.type,
        granted_by_id=granted_by.id,
        authority_basis=authority_basis,
        workspace_id=scope.workspace_id,
        granted_at=now(),
        expires_at=expires_at,
    )
    session.add(grant)
    await session.flush()

    # 🔒 consent_rules ข้อ 2: การให้ · การใช้ · และการเพิกถอน ต้องออก audit event ทุกครั้ง
    #    (เราขาดข้อนี้มาตลอดจนกระทั่ง event/v1 v1.6.0 มี event type ให้ใช้)
    from care_addons.ap_audit import services as audit

    await audit.emit(
        session,
        scope,
        event_type="CONSENT_GRANTED",
        subject_type="record",
        subject_id=grant.grant_id,
        attributes={
            "record_type": "consent_grant",
            "subject_id": grant.subject_id,
            "grantee_id": grant.grantee_id,
            "scopes": list(grant.scopes or []),
            "purpose": grant.purpose,
            "conditions": [c.get("kind") for c in (grant.conditions or [])],
            "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        },
    )
    return grant


async def revoke_consent(
    session: AsyncSession, scope: TenantScope, grant_id: str, *, reason: str
) -> None:
    """เพิกถอนความยินยอม — มีผลทันที

    `reason` บังคับตาม consent/v1 (`dependentRequired`) เพราะ "ถอนเพราะเจ้าของเปลี่ยนใจ"
    กับ "ถอนเพราะผู้รับละเมิดเงื่อนไข" ต่างกันมากตอน audit
    """
    if not reason or not reason.strip():
        raise ValueError("การเพิกถอนต้องระบุเหตุผล — consent/v1 บังคับ revoked_reason")
    grant = await session.get(ApConsentGrant, grant_id)
    if grant is None:
        raise ConsentDenied(f"ไม่พบ consent grant: {grant_id}")
    assert_same_tenant(scope, grant)
    grant.revoked_at = now()
    grant.revoked_by_type = scope.principal.type
    grant.revoked_by_id = scope.principal.id
    grant.revoked_reason = reason.strip()
    await session.flush()

    from care_addons.ap_audit import services as audit

    await audit.emit(
        session,
        scope,
        event_type="CONSENT_REVOKED",
        subject_type="record",
        subject_id=grant.grant_id,
        transition={"from": "active", "to": "revoked", "reason": grant.revoked_reason},
        attributes={
            "record_type": "consent_grant",
            "subject_id": grant.subject_id,
            "grantee_id": grant.grantee_id,
            "scopes": list(grant.scopes or []),
        },
    )


# ── เงื่อนไขที่ต้องยังเป็นจริงตอนเข้าถึง ────────────────────────────────────────
# 🔒 โมดูลนี้ไม่รู้ว่าเงื่อนไขชนิดหนึ่ง ๆ แปลว่าอะไร — โดเมนลงทะเบียนตัวตรวจเอง
_CONDITIONS: dict[str, Any] = {}


def register_condition(kind: str, checker: Any) -> None:
    """checker(session, scope, condition: dict) -> bool

    คืน False = ใบนี้ใช้ไม่ได้ **ตอนนี้** (ไม่ใช่ถูกเพิกถอน) · ต้องไม่ raise
    เงื่อนไขที่พังต้องแปลว่า "ไม่ให้ผ่าน" ไม่ใช่ "ปล่อยผ่านเพราะตรวจไม่ได้"
    """
    _CONDITIONS[kind] = checker


def condition_checker(kind: str) -> Any:
    return _CONDITIONS.get(kind)


async def conditions_hold(
    session: AsyncSession, scope: TenantScope, grant: ApConsentGrant
) -> bool:
    """เงื่อนไขทุกข้อของใบนี้ยังเป็นจริงไหม — 🔒 fail closed ทุกทาง"""
    for condition in grant.conditions or []:
        kind = (condition or {}).get("kind")
        checker = condition_checker(kind)
        if checker is None:
            # ไม่รู้จักเงื่อนไข = ไม่อนุญาต (หลักเดียวกับ scope ที่ไม่รู้จักใน consent/v1)
            logger.warning("consent grant %s มีเงื่อนไขที่ไม่มีใครตรวจได้: %r", grant.grant_id, kind)
            return False
        try:
            if not await checker(session, scope, condition):
                return False
        except Exception:
            logger.exception("ตรวจเงื่อนไข %r ของ grant %s ไม่สำเร็จ", kind, grant.grant_id)
            return False
    return True


def _remember_evaluation(session: AsyncSession, evaluation: dict) -> None:
    """แช่แข็งผลไว้ให้ event ถัดไปหยิบไปแนบ (consent/v1 $defs.Evaluation)

    🔒 การรู้แค่ `grant_id` แล้วไปประเมินใหม่ทีหลังจะได้คำตอบของ *วันที่ประเมิน*
       ไม่ใช่ของ *วันที่เข้าถึง* — หมอที่ลาออกไปแล้ววันนี้จะทำให้ replay สรุปว่า
       การเข้าถึงเมื่อปีที่แล้วไม่ชอบ ทั้งที่ตอนนั้นเขายังสังกัดอยู่ (ADR-0016)
    """
    session.info[EVALUATION_KEY] = evaluation


def take_evaluation(session: AsyncSession) -> dict | None:
    """หยิบผลล่าสุดออกมา **ครั้งเดียว** — กันไม่ให้ไปติดกับ event อื่นที่ไม่เกี่ยวกัน"""
    return session.info.pop(EVALUATION_KEY, None)


async def has_consent(
    session: AsyncSession, scope: TenantScope, *, subject_id: str, required_scope: str
) -> bool:
    """subject เข้าถึงข้อมูลของตัวเองได้เสมอ · นอกนั้นต้องมี grant ที่ยังไม่หมดอายุ/ไม่ถูกเพิกถอน"""
    if scope.principal.id == subject_id:
        return True

    result = await session.execute(
        scoped(
            select(ApConsentGrant).where(
                ApConsentGrant.subject_id == subject_id,
                ApConsentGrant.grantee_id == scope.principal.id,
                # ไม่มีคอลัมน์ status — สถานะคือผลของ revoked_at/expires_at เท่านั้น
                ApConsentGrant.revoked_at.is_(None),
            ),
            ApConsentGrant,
            scope,
        )
    )
    current = now()
    for grant in result.scalars():
        if grant.revoked_at is not None:
            continue
        if grant.expires_at is not None and grant.expires_at <= current:
            continue
        if required_scope not in (grant.scopes or []) and "care.manage" not in (grant.scopes or []):
            continue
        checked = [c.get("kind") for c in (grant.conditions or []) if c.get("kind")]
        satisfied = await conditions_hold(session, scope, grant)
        # บันทึกทั้งผ่านและไม่ผ่าน — `satisfied: false` ไม่ได้แปลว่าใบไม่มีอยู่
        # แต่แปลว่าตอนนั้นใช้ไม่ได้ (consent/v1 $defs.Evaluation)
        _remember_evaluation(
            session,
            {
                "grant_id": grant.grant_id,
                "evaluated_at": current.isoformat(),
                "satisfied": satisfied,
                **({"conditions_checked": checked} if checked else {}),
            },
        )
        if not satisfied:
            continue
        return True
    return False


def as_consent_grant(grant: ApConsentGrant) -> dict:
    """payload ตาม `consent/v1` — ใช้ส่งออกนอกระบบและให้ payload_check validate"""
    payload: dict = {
        "grant_id": grant.grant_id,
        "tenant_id": grant.tenant_id,
        "subject_id": grant.subject_id,
        "grantee": {"type": grant.grantee_type, "id": grant.grantee_id},
        "scopes": list(grant.scopes or []),
        "purpose": grant.purpose,
        "granted_by": {"type": grant.granted_by_type, "id": grant.granted_by_id},
        "granted_at": grant.granted_at.isoformat(),
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
    }
    if grant.conditions:
        # ไม่ได้อยู่ใน consent/v1 — เราเติมเพราะใบที่มีเงื่อนไขแต่ payload ไม่บอก
        # จะทำให้ consumer เข้าใจว่าใบนี้ใช้ได้ตลอดจนหมดอายุ ซึ่งไม่จริง
        payload["conditions"] = grant.conditions
    if grant.workspace_id:
        payload["workspace_id"] = grant.workspace_id
    if grant.authority_basis:
        payload["authority_basis"] = grant.authority_basis
    if grant.revoked_at:
        payload["revoked_at"] = grant.revoked_at.isoformat()
        payload["revoked_by"] = {"type": grant.revoked_by_type, "id": grant.revoked_by_id}
        payload["revoked_reason"] = grant.revoked_reason
    return payload


async def require_consent(
    session: AsyncSession, scope: TenantScope, *, subject_id: str, required_scope: str
) -> None:
    """ผ่านหรือ raise — และ **ไม่ว่าทางไหนผลการประเมินต้องไม่ค้างอยู่ใน session**

    🔒 การเข้าถึงที่ถูกปฏิเสธคือสิ่งที่ audit ต้องบันทึกที่สุด — ไม่ใช่สิ่งที่หายไปเงียบ ๆ
       และถ้าไม่บันทึกตรงนี้ ผลที่แช่แข็งไว้จะไปติดกับ event ถัดไปที่ไม่เกี่ยวข้องกัน
    """
    if await has_consent(session, scope, subject_id=subject_id, required_scope=required_scope):
        return

    from care_addons.ap_audit import services as audit

    await audit.emit(
        session,
        scope,
        event_type="EXECUTION_FAILED",
        subject_type="record",
        subject_id=subject_id,
        error=audit.make_error(
            "care.consent.denied",
            "authorization",
            f"ไม่มีความยินยอม '{required_scope}' สำหรับข้อมูลของ subject นี้",
            retryable=False,
        ),
        attributes={"record_type": "consent_check", "required_scope": required_scope},
    )
    raise ConsentDenied(
        f"{scope.principal.id} ไม่มี consent '{required_scope}' สำหรับ {subject_id}"
    )
