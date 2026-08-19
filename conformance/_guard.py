"""ด่านกันสคริปต์ที่ **ลบข้อมูลทั้ง schema** ไปโดนฐานข้อมูลจริง

`migration_check` · `payload_check` · `rls_check` เริ่มงานด้วย `DROP SCHEMA public CASCADE`
เพราะต้องพิสูจน์จากฐานข้อมูลเปล่าจริง ๆ ว่า migration/RLS สร้างของครบเอง

ปัญหาคือสคริปต์เหล่านี้ถูก copy เข้า Docker image (เพื่อให้รัน `db_role_check` จากใน
เครือข่ายเดียวกับ DB ได้) — ผู้ดูแลที่ exec เข้า container แล้วรัน `rls_check` เพื่อ
"ตรวจว่า RLS ยังทำงานอยู่ไหม" จะลบข้อมูลผู้ป่วยทั้งหมดโดยไม่มีคำเตือน
เจอจริงตอนทดสอบ `docker compose up` ของ M5

🔒 default คือ **ปฏิเสธ** — การลบข้อมูลต้องมีเจตนาที่พิมพ์ออกมาเป็นตัวอักษรเสมอ
"""

from __future__ import annotations

import os
import sys

ALLOW_ENV = "CONFORMANCE_ALLOW_DESTRUCTIVE"

SAFE_SCRIPTS = ("db_role_check.py", "drift_check.py")


def require_destructive_consent(script: str, url: str) -> None:
    """เรียกก่อน DROP SCHEMA ทุกครั้ง — ออกจากโปรแกรมถ้าไม่ได้ตั้งใจ

    sqlite ไม่ต้องผ่านด่านนี้เพราะแต่ละสคริปต์ใช้ไฟล์ .db ของตัวเองที่ลบทิ้งได้
    """
    if not url.startswith("postgresql"):
        return
    if os.environ.get(ALLOW_ENV) == "1":
        return
    print(
        f"✗ {script} จะรัน DROP SCHEMA public CASCADE บน {_redact(url)}\n"
        f"  ซึ่งลบข้อมูลทั้งหมดในฐานข้อมูลนั้น — สคริปต์นี้ออกแบบมาสำหรับ DB ที่ทิ้งได้เท่านั้น\n"
        f"\n"
        f"  ถ้านี่คือ CI หรือฐานข้อมูลทดสอบ: ตั้ง {ALLOW_ENV}=1 แล้วรันใหม่\n"
        f"  ถ้ากำลังตรวจ deployment จริง: รันได้เฉพาะ {', '.join(SAFE_SCRIPTS)} ซึ่งอ่านอย่างเดียว",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _redact(url: str) -> str:
    """ตัดรหัสผ่านออกก่อนพิมพ์ — ข้อความ error ไม่ควรกลายเป็นที่รั่วของ credential"""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host = rest.partition("@")
    return f"{scheme}://***@{host}"
