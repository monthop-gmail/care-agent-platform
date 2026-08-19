"""shim — tenancy primitives ขึ้น kernel แล้ว (pstack v0.3.0 · pstack#3)

รอบที่ 1 ตาม ADR-0003: ไฟล์นี้ re-export ของจาก kernel ให้ 111 จุดเดิมยังใช้ได้
รอบที่ 2 จะแก้ import ที่ต้นทางแล้วลบโมดูลนี้

ของที่ **ไม่ได้** ขึ้น kernel และย้ายไป `ap_consent` แทน — consent เป็น governance
ไม่ใช่ infra (ข้อสรุปเดียวกับที่เราตอบ pstack#3 และ agent-platform#15 → consent/v1)
"""

from addons.tenancy.services import (
    add_member,
    create_tenant,
    create_workspace,
    is_member,
    member_role,
    tenants_of,
)
from core.tenancy import (
    Principal,
    TenantIsolationError,
    TenantScope,
    assert_same_tenant,
    scoped,
)

from care_addons.ap_consent.services import (
    ConsentDenied,
    as_consent_grant,
    grant_consent,
    has_consent,
    require_consent,
    revoke_consent,
)

__all__ = [
    "ConsentDenied",
    "Principal",
    "TenantIsolationError",
    "TenantScope",
    "add_member",
    "as_consent_grant",
    "assert_same_tenant",
    "create_tenant",
    "create_workspace",
    "grant_consent",
    "has_consent",
    "is_member",
    "member_role",
    "require_consent",
    "revoke_consent",
    "scoped",
    "tenants_of",
]
