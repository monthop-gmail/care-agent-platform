#!/usr/bin/env python3
"""ตรวจว่า role ที่แอปใช้ต่อ DB ไม่ใช่ superuser และไม่มี BYPASSRLS

ทำไมต้องมี: **RLS ถูก bypass เสมอโดย superuser** และ `FORCE ROW LEVEL SECURITY`
คุมได้แค่ table owner ไม่ได้คุม superuser — ถ้าแอปต่อ DB ด้วย superuser
tenant isolation ชั้น DB จะไม่ทำงานเลย **โดยไม่มี error และเทสยังเขียวหมด**
เพราะ `scoped()` กันไว้อีกชั้น (ADR-0007 · care-agent-platform#1)

เทส conformance ของ pstack พิสูจน์ว่า FORCE ทำงานกับ role ธรรมดา — แต่พิสูจน์ไม่ได้
ว่า *role ที่ deployment นี้ใช้จริง* เป็น role ธรรมดา สคริปต์นี้ปิดช่องนั้น

รัน:
    python conformance/db_role_check.py

ข้ามเองถ้า PSTACK_DATABASE_URL ไม่ใช่ Postgres (sqlite ไม่มี RLS — architecture/stack.md)
"""

from __future__ import annotations

import asyncio
import os
import sys

QUERY = "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"


async def check(url: str) -> int:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(sa.text(QUERY))).one_or_none()
            user = (await conn.execute(sa.text("SELECT current_user"))).scalar_one()
    finally:
        await engine.dispose()

    if row is None:
        print(f"✗ หา role '{user}' ใน pg_roles ไม่เจอ — ตรวจไม่ได้", file=sys.stderr)
        return 1

    problems = []
    if row.rolsuper:
        problems.append(f"'{user}' เป็น superuser — RLS ถูก bypass ทั้งหมด")
    if row.rolbypassrls:
        problems.append(f"'{user}' มี BYPASSRLS — RLS ไม่มีผล")

    if problems:
        print("✗ role ที่แอปใช้ต่อ DB ทำให้ RLS ไร้ผล:", file=sys.stderr)
        for p in problems:
            print(f"   {p}", file=sys.stderr)
        print(
            "\n   แก้: ให้ POSTGRES_USER เป็น superuser สำหรับ bootstrap เท่านั้น\n"
            "   แล้วให้แอปต่อด้วย role ที่สร้างแบบ NOSUPERUSER NOBYPASSRLS\n"
            "   (deploy/db-init/10-app-role.sh · README หัวข้อ 'ย้าย deployment เดิม...')",
            file=sys.stderr,
        )
        return 1

    print(f"✓ role '{user}' ไม่ใช่ superuser และไม่มี BYPASSRLS — RLS มีผลจริง")
    return 0


def main() -> int:
    url = os.environ.get("PSTACK_DATABASE_URL", "")
    if not url:
        print("✗ ไม่ได้ตั้ง PSTACK_DATABASE_URL", file=sys.stderr)
        return 1
    if not url.startswith("postgresql"):
        print("ℹ ข้าม — ไม่ใช่ Postgres (sqlite ไม่มี RLS)")
        return 0
    return asyncio.run(check(url))


if __name__ == "__main__":
    raise SystemExit(main())
