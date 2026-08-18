"""FastAPI dependency สำหรับ resolve TenantScope

request ที่ resolve tenant ไม่ได้ → ปฏิเสธ **ห้ามเดา tenant ให้**
(invariant ของ event/v1 ที่เราขยายมาใช้กับ request ด้วย)
"""

from __future__ import annotations

from typing import Annotated, Any

from core.auth import get_current_user
from core.db import get_session
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_tenancy.services import Principal, TenantScope, is_member


def principal_of(user: Any) -> Principal:
    return Principal(
        type="human",
        id=f"user-{user.id}",
        display_name=getattr(user, "full_name", "") or getattr(user, "email", ""),
    )


async def get_scope(
    user: Annotated[Any, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> TenantScope:
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ต้องระบุ X-Tenant-Id — ระบบไม่เดา tenant ให้",
        )
    if not getattr(user, "is_superuser", False) and not await is_member(
        session, x_tenant_id, user.id
    ):
        # ตอบ 404 ไม่ใช่ 403 — ไม่ยืนยันว่า tenant นี้มีอยู่จริงให้คนนอกรู้
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบ tenant")
    return TenantScope(
        tenant_id=x_tenant_id,
        principal=principal_of(user),
        correlation_id=x_correlation_id,
    )


ScopeDep = Annotated[TenantScope, Depends(get_scope)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
