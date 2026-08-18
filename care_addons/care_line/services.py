"""จับคู่บัญชี LINE + ส่งข้อความออก

transport ถูกแยกออกมาเป็นตัวแปรระดับโมดูลเพื่อให้เทสสลับได้ — ไม่งั้นการทดสอบ
ทุกอย่างต้องยิง LINE API จริง ซึ่งทำใน CI ไม่ได้
"""

from __future__ import annotations

import logging
import secrets
import string
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_tenancy.clock import now
from care_addons.ap_tenancy.ids import new_id
from care_addons.ap_tenancy.services import Principal, TenantScope, scoped
from care_addons.care_line.models import ROLES, CareLineBinding, CareLinePairingCode

logger = logging.getLogger(__name__)

CODE_ALPHABET = string.ascii_uppercase + string.digits
CODE_TTL_MINUTES = 60


class PairingError(ValueError):
    pass


async def _line_transport(channel_id: str, line_user_id: str, text: str) -> tuple[bool, str | None]:
    """ส่งจริงผ่าน LINE Messaging API ของ pstack"""
    from addons.line_oa import client as line_client
    from addons.line_oa.models import LineChannel
    from core.db import get_sessionmaker

    async with get_sessionmaker()() as db:
        result = await db.execute(select(LineChannel).where(LineChannel.channel_id == channel_id))
        channel = result.scalar_one_or_none()
        if channel is None:
            return False, f"ไม่พบ LINE channel {channel_id} ในระบบ"
        token = channel.access_token

    ok = await line_client.push(token, line_user_id, [line_client.text_message(text)])
    return ok, None if ok else "LINE API ปฏิเสธข้อความ"


# เทสสลับตัวนี้เพื่อดักข้อความแทนการยิง LINE API จริง
transport = _line_transport


async def create_pairing_code(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    principal_id: str,
    role: str,
    display_name: str = "",
    ttl_minutes: int = CODE_TTL_MINUTES,
) -> CareLinePairingCode:
    if role not in ROLES:
        raise PairingError(f"role ไม่รู้จัก: {role}")
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
    record = CareLinePairingCode(
        code=code,
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        principal_id=principal_id,
        role=role,
        display_name=display_name,
        created_by=scope.principal.id,
        expires_at=now() + timedelta(minutes=ttl_minutes),
    )
    session.add(record)
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="artifact",
        subject_id=patient_id,
        transition={"from": None, "to": "pairing_code_issued", "reason": role},
        attributes={
            "record_type": "line_pairing_code",
            "patient_id": patient_id,
            "role": role,
            "principal_id": principal_id,
            # 🔒 ไม่บันทึกตัวโค้ดลง audit — ใครอ่าน log ได้จะผูกบัญชีแทนได้ทันที
        },
    )
    return record


async def redeem_pairing_code(
    session: AsyncSession, *, code: str, channel_id: str, line_user_id: str, display_name: str = ""
) -> CareLineBinding:
    """แลกโค้ดเป็นการผูกบัญชี — ยังไม่มี tenant scope ตอนเข้ามา จึงต้อง resolve จากโค้ดเอง"""
    record = await session.get(CareLinePairingCode, code.strip().upper())
    if record is None:
        raise PairingError("โค้ดไม่ถูกต้อง")
    if record.used_at is not None:
        raise PairingError("โค้ดนี้ถูกใช้ไปแล้ว")
    if record.expires_at <= now():
        raise PairingError("โค้ดหมดอายุแล้ว")

    scope = TenantScope(
        tenant_id=record.tenant_id,
        principal=Principal(type="service", id="care-line"),
    )

    existing = await session.execute(
        select(CareLineBinding).where(
            CareLineBinding.channel_id == channel_id,
            CareLineBinding.line_user_id == line_user_id,
        )
    )
    binding = existing.scalar_one_or_none()
    if binding is not None:
        # ผูกซ้ำ = ย้ายไปผู้ป่วยรายใหม่ (เช่นเปลี่ยนเครื่อง/เปลี่ยนผู้ดูแล) — บันทึกไว้เสมอ
        binding.tenant_id = record.tenant_id
        binding.principal_id = record.principal_id
        binding.role = record.role
        binding.patient_id = record.patient_id
        binding.display_name = display_name or record.display_name
        binding.active = True
    else:
        binding = CareLineBinding(
            binding_id=new_id("lb"),
            tenant_id=record.tenant_id,
            channel_id=channel_id,
            line_user_id=line_user_id,
            principal_id=record.principal_id,
            role=record.role,
            patient_id=record.patient_id,
            display_name=display_name or record.display_name,
        )
        session.add(binding)

    record.used_at = now()
    await session.flush()

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="artifact",
        subject_id=binding.patient_id,
        transition={"from": None, "to": "line_bound", "reason": binding.role},
        attributes={
            "record_type": "line_binding",
            "patient_id": binding.patient_id,
            "role": binding.role,
            "principal_id": binding.principal_id,
        },
    )
    return binding


async def find_binding(
    session: AsyncSession, *, channel_id: str, line_user_id: str
) -> CareLineBinding | None:
    result = await session.execute(
        select(CareLineBinding).where(
            CareLineBinding.channel_id == channel_id,
            CareLineBinding.line_user_id == line_user_id,
            CareLineBinding.active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def binding_for_principal(
    session: AsyncSession, scope: TenantScope, principal_id: str
) -> CareLineBinding | None:
    result = await session.execute(
        scoped(
            select(CareLineBinding).where(
                CareLineBinding.principal_id == principal_id,
                CareLineBinding.active.is_(True),
            ),
            CareLineBinding,
            scope,
        )
    )
    return result.scalars().first()


async def send_text(
    session: AsyncSession, scope: TenantScope, principal_id: str, text: str
) -> tuple[bool, str | None]:
    binding = await binding_for_principal(session, scope, principal_id)
    if binding is None:
        return False, f"{principal_id} ยังไม่ได้ผูกบัญชี LINE"
    return await transport(binding.channel_id, binding.line_user_id, text)
