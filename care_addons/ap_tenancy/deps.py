"""shim — dependency ของ scope ขึ้น kernel แล้ว (`addons.tenancy.deps`)

`get_scope` ของ kernel ตั้ง GUC `pstack.tenant_id` ต่อ transaction ให้ด้วย
ซึ่งเป็นสิ่งที่ RLS policy อ่าน — ของเดิมของเราไม่ได้ทำ
"""

from addons.tenancy.deps import ScopeDep, SessionDep, get_scope, principal_of

__all__ = ["ScopeDep", "SessionDep", "get_scope", "principal_of"]
