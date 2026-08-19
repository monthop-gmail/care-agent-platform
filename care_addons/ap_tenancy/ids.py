"""shim — id format ย้ายขึ้น kernel เป็น `core.tenancy` แล้ว (pstack v0.3.0)

`core.tenancy.ID_PATTERN` ตั้งใจให้ตรงกับ `identity/v1 $defs.Id` ของ agent-platform
และเรามีเทสล็อกไว้ที่ `tests/test_kernel_contract_lock.py` ว่ายังตรงกันจริง
— ถ้า kernel ขยับ pattern เมื่อไร CI ของเราแดงทันที ไม่ต้องรอไปเจอตอน validate payload
"""

from core.tenancy import ID_PATTERN, InvalidId, new_id, validate_id

__all__ = ["ID_PATTERN", "InvalidId", "new_id", "validate_id"]
