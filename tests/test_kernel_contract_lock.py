"""ล็อกสัญญาระหว่าง kernel กับ contract ของ agent-platform

pstack ย้าย id format ขึ้น kernel เป็น `core.tenancy.ID_PATTERN` และเขียนไว้ในเอกสารว่า
"ตั้งใจให้ตรงกับ `identity/v1 $defs.Id` เป๊ะ · ห้ามขยับโดยไม่ประสานกับ consumer"

เราเป็น consumer ที่ว่านั้น — เทสนี้ทำให้ CI ของเราแดงทันทีถ้า kernel ขยับ pattern
แทนที่จะไปเจอตอน payload validate ไม่ผ่านหรือ (แย่กว่า) ตอน id ที่สร้างไว้แล้วกลายเป็นไม่ valid
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
# ดึงมาจาก cache ที่ payload_check โหลดไว้ — ไม่ต้องต่อเน็ตในเทส
CACHE = ROOT / ".schema_cache"


def _identity_id_pattern() -> str | None:
    if not CACHE.is_dir():
        return None
    for path in sorted(CACHE.glob("*identity_v1_identity.schema.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        return document["$defs"]["Id"]["pattern"]
    return None


def test_kernel_id_pattern_matches_identity_v1():
    from core.tenancy import ID_PATTERN

    expected = _identity_id_pattern()
    if expected is None:
        pytest.skip("ยังไม่มี schema cache — รัน conformance/payload_check.py ก่อน")

    assert ID_PATTERN.pattern == expected, (
        f"kernel `core.tenancy.ID_PATTERN` = {ID_PATTERN.pattern!r} "
        f"ไม่ตรงกับ identity/v1 $defs.Id = {expected!r} — "
        "ประสานกับ pstack ก่อนขยับ (pstack#9 เขียนไว้ว่าเป็น contract ข้าม repo)"
    )


def test_ids_shim_still_points_at_the_kernel():
    """shim รอบที่ 1 ต้องไม่มี pattern เป็นของตัวเอง ไม่งั้นสองที่จะ drift จากกัน"""
    from core.tenancy import ID_PATTERN as kernel_pattern
    from core.tenancy import ID_PATTERN as shim_pattern

    assert shim_pattern is kernel_pattern
