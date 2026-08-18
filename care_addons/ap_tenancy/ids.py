"""รูปแบบ id กลางของ platform — identity/v1 $defs.Id

ห้ามนิยามรูปแบบ id เองที่อื่น (ADR-0001) — ทุก addon ใช้ helper ในไฟล์นี้
"""

from __future__ import annotations

import re
import uuid

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class InvalidId(ValueError):
    pass


def validate_id(value: str, field: str = "id") -> str:
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        raise InvalidId(
            f"{field} ไม่ตรงรูปแบบ identity/v1 $defs.Id "
            f"(lowercase, ขึ้นต้นด้วย alphanumeric, ยาวไม่เกิน 63): {value!r}"
        )
    return value


def new_id(prefix: str) -> str:
    """สร้าง id ใหม่ที่ตรง pattern — prefix ช่วยให้อ่าน log ออกว่าเป็นของอะไร"""
    return validate_id(f"{prefix}-{uuid.uuid4().hex[:16]}", prefix)
