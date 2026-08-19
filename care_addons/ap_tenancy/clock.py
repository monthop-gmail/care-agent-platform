"""shim — นาฬิกาย้ายขึ้น kernel เป็น `core.clock` แล้ว (pstack v0.3.0)

เก็บไฟล์นี้ไว้หนึ่งรอบตาม ADR-0003 เพราะมี 16 จุดที่ import จากที่นี่
รอบที่ 2 ให้เปลี่ยนเป็น `from core.clock import now, FakeClock` แล้วลบไฟล์นี้
"""

from core.clock import FakeClock, now, set_now

__all__ = ["FakeClock", "now", "set_now"]
