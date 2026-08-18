"""นาฬิกาของระบบ — ทุกที่ต้องเรียกผ่านที่นี่ ห้ามเรียก datetime.now() ตรง

เหตุผล: scenario test ต้องเลื่อนเวลาไปข้างหน้าเพื่อทดสอบ retry / missed / escalation
ถ้าโค้ดเรียก datetime.now() เอง จะเทสวงจร closed-loop ไม่ได้เลย

    from care_addons.ap_tenancy.clock import now, FakeClock

    with FakeClock("2026-08-19T07:00:00+07:00") as clk:
        ...
        clk.advance(minutes=45)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Self

_override: datetime | None = None


def now() -> datetime:
    return _override if _override is not None else datetime.now(UTC)


def set_now(value: datetime | str | None) -> None:
    global _override
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value is not None and value.tzinfo is None:
        raise ValueError("เวลาที่ตั้งต้องมี timezone — naive datetime ทำให้ routine เพี้ยนข้ามโซน")
    _override = value


class FakeClock:
    """ใช้ในเทสเท่านั้น"""

    def __init__(self, start: datetime | str) -> None:
        self.start = datetime.fromisoformat(start) if isinstance(start, str) else start

    def __enter__(self) -> Self:
        set_now(self.start)
        return self

    def __exit__(self, *exc: object) -> None:
        set_now(None)

    def advance(self, **kwargs: float) -> datetime:
        current = now() + timedelta(**kwargs)
        set_now(current)
        return current

    def set(self, value: datetime | str) -> datetime:
        set_now(value)
        return now()
