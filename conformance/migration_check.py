#!/usr/bin/env python3
"""ตรวจว่า Alembic migration ยังตรงกับ models

ถ้าใครแก้ `models.py` แล้วลืมสร้าง migration ระบบจะยังรันได้บนเครื่องตัวเอง (DB เก่ามีตารางอยู่แล้ว)
แล้วไปพังตอน deploy ขึ้นเครื่องใหม่ — สคริปต์นี้ทำให้ CI จับได้ตั้งแต่ PR

    python conformance/migration_check.py

ใช้ DB จาก PSTACK_DATABASE_URL (ค่าเริ่มต้นเป็น sqlite ชั่วคราว) โดยสร้างจาก migration ล้วน ๆ
แล้วเทียบกับ Base.metadata ด้วย alembic compare_metadata
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for candidate in (ROOT / "pstack_src", ROOT.parent / "pstack"):
    if (candidate / "addons").is_dir():
        os.environ.setdefault("PSTACK_ADDONS_PATHS", f"{candidate / 'addons'},care_addons")
        sys.path.insert(0, str(candidate))
        break

CHECK_DB = ROOT / "migration_check.db"
os.environ.setdefault("PSTACK_DATABASE_URL", f"sqlite+aiosqlite:///{CHECK_DB}")
os.environ.setdefault("PSTACK_SECRET_KEY", "migration-check")
os.environ.setdefault(
    "PSTACK_MODULES",
    "users,ap_tenancy,ap_audit,ap_policy,care_patient,care_escalation,"
    "care_routine,care_medication,care_journal",
)

IGNORED_TABLE_PREFIXES = ("alembic_version",)


def _relevant(diff) -> bool:
    """กรอง diff ที่ไม่เกี่ยวกับ schema ของเรา"""
    entries = diff if isinstance(diff, list) else [diff]
    for entry in entries:
        name = ""
        if entry[0] in ("add_table", "remove_table"):
            name = entry[1].name
        elif len(entry) > 2 and isinstance(entry[2], str):
            name = entry[2]
        if name.startswith(IGNORED_TABLE_PREFIXES):
            return False
    return True


async def main() -> int:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from core.app import create_app  # core.app เรียก logging.basicConfig ตอน import
    from core.db import Base, dispose_engine, get_engine, get_sessionmaker
    from core.registry import create_core_tables, sync_modules
    from core.runtime import ctx

    logging.getLogger().setLevel(logging.WARNING)   # เอา log การติดตั้งโมดูลออก เหลือแต่ผลตรวจ

    url = os.environ["PSTACK_DATABASE_URL"]
    if url.startswith("sqlite") and CHECK_DB.exists():
        CHECK_DB.unlink()

    create_app()
    engine = get_engine()

    if not url.startswith("sqlite"):
        from sqlalchemy import text

        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))

    # สร้าง schema จาก migration ล้วน ๆ (ไม่ใช่ create_all)
    await create_core_tables(engine)
    async with get_sessionmaker()() as session:
        await sync_modules(engine, session, ctx.load_order)

    async with engine.connect() as conn:
        diffs = await conn.run_sync(
            lambda sync_conn: compare_metadata(
                MigrationContext.configure(sync_conn), Base.metadata
            )
        )

    await dispose_engine()
    if url.startswith("sqlite") and CHECK_DB.exists():
        CHECK_DB.unlink()

    relevant = [d for d in diffs if _relevant(d)]
    if relevant:
        print("✗ migration ไม่ตรงกับ models — สร้าง revision ใหม่ก่อน merge:")
        for diff in relevant:
            print(f"   {diff}")
        print("\n   python ../pstack/cli.py makemigration <module> -m 'อธิบายการเปลี่ยนแปลง'")
        return 1

    modules_with_migrations = sorted(
        m.name for m in ctx.load_order if (m.path / "migrations").is_dir()
    )
    print(f"✓ migration ตรงกับ models — {len(modules_with_migrations)} โมดูล: {', '.join(modules_with_migrations)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
