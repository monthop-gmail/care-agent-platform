"""บูต pstack + care_addons บน sqlite แล้วให้ session/scope กับเทส

pstack ต้องอยู่ที่ ../pstack หรือ ./pstack_src (CI) หรือ override ด้วย PSTACK_ADDONS_PATHS
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if "PSTACK_ADDONS_PATHS" not in os.environ:
    for candidate in (ROOT / "pstack_src", ROOT.parent / "pstack"):
        if (candidate / "addons").is_dir():
            os.environ["PSTACK_ADDONS_PATHS"] = f"{candidate / 'addons'},care_addons"
            sys.path.insert(0, str(candidate))
            break

MODULES = [
    "users",
    "tenancy",
    "ap_consent",
    "ap_tenancy",
    "ap_audit",
    "ap_policy",
    "care_patient",
    "care_escalation",
    "care_routine",
    "care_medication",
    "care_journal",
    "care_appointment",
    "care_orientation",
    "line_oa",
    "care_line",
]

# CI รันชุดเดียวกันสองรอบ: sqlite (เร็ว) และ Postgres (ตรงกับ production)
# ตั้ง PSTACK_DATABASE_URL มาก่อนได้เพื่อชี้ไป Postgres
os.environ.setdefault("PSTACK_DATABASE_URL", "sqlite+aiosqlite:///./test_care.db")
os.environ.setdefault("PSTACK_SECRET_KEY", "test-secret")
os.environ["PSTACK_MODULES"] = ",".join(MODULES)

import pytest
import pytest_asyncio
from core.app import create_app
from fastapi.testclient import TestClient

from care_addons.ap_tenancy import services as tenancy
from care_addons.ap_tenancy.clock import set_now

DB_FILE = ROOT / "test_care.db"
DATABASE_URL = os.environ["PSTACK_DATABASE_URL"]
ON_SQLITE = DATABASE_URL.startswith("sqlite")


def _reset_database() -> None:
    """เริ่มจาก DB ว่างเสมอ — ไม่งั้น alembic เห็นตารางเดิมแล้วข้ามการติดตั้ง"""
    if ON_SQLITE:
        DB_FILE.unlink(missing_ok=True)
        return

    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _drop_schema() -> None:
        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(_drop_schema())


@pytest.fixture(scope="session")
def app():
    _reset_database()
    application = create_app()
    with TestClient(application) as client:      # lifespan รัน migration + hooks ของทุกโมดูล
        yield application, client
    if ON_SQLITE:
        DB_FILE.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def client(app):
    return app[1]


@pytest_asyncio.fixture
async def session(app):
    """engine ของเทสเอง ไม่ใช่ engine global ของ kernel

    เหตุผล: `TestClient` รัน lifespan ในลูปของตัวเอง และ engine global ที่ถูกสร้างตรงนั้น
    จะผูกกับลูปนั้นถาวร พอเทส async ตัวถัดไป (คนละ event loop) หยิบไปใช้ asyncpg จะโยน
    "attached to a different loop" ทันที — aiosqlite ไม่โยนเพราะทำงานบน thread
    (เจอตอนเปิด Postgres ใน CI: sqlite ผ่านหมด Postgres พังหนึ่งตัวพอดี)
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(DATABASE_URL)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()
    set_now(None)


def scope_for(tenant_id: str, principal_id: str = "user-1", correlation_id: str | None = None):
    return tenancy.TenantScope(
        tenant_id=tenant_id,
        principal=tenancy.Principal(type="human", id=principal_id, display_name="tester"),
        correlation_id=correlation_id,
    )


def system_scope(tenant_id: str):
    """scope ของ orchestrator ที่เดิน closed loop"""
    return tenancy.TenantScope(
        tenant_id=tenant_id,
        principal=tenancy.Principal(type="service", id="care-orchestrator"),
    )


async def use_tenant(session, tenant_id: str) -> None:
    """ตั้ง GUC ของ RLS ให้ session ในเทส

    บน Postgres ตารางโดเมนเปิด RLS ไว้ (care-agent-platform#4) — ไม่ตั้ง GUC = เห็น 0 แถว
    บน sqlite เป็น no-op · เทสที่ใช้หลาย tenant ต้องเรียกสลับเองก่อนแตะข้อมูลของแต่ละ tenant
    """
    from core.tenancy import bind_tenant

    await bind_tenant(session, tenant_id)


@pytest_asyncio.fixture
async def tenant(session):
    """tenant + membership + consent ครบสำหรับเทสหนึ่งตัว"""
    import uuid

    tenant_id = f"t-{uuid.uuid4().hex[:8]}"
    await tenancy.create_tenant(session, tenant_id, "Test Family")
    await session.commit()
    await use_tenant(session, tenant_id)   # เทสเกือบทั้งหมดใช้ tenant เดียว
    return tenant_id


async def setup_patient(
    session,
    tenant_id: str,
    *,
    profile: dict | None = None,
    timezone: str = "Asia/Bangkok",
    with_caregiver: bool = True,
    quiet_hours: tuple[str, str] | None = None,
):
    """สร้างผู้ป่วย + consent ให้ผู้ดูแล + ทีมดูแล — ชุดเริ่มต้นของ scenario test

    ตั้งใจให้ผ่าน consent ตั้งแต่ต้น เพราะ scenario ส่วนใหญ่ทดสอบ care loop ไม่ใช่ consent
    (การทดสอบว่า consent กันได้จริงอยู่ที่ tests/test_tenant_isolation.py)
    """
    from care_addons.care_patient import services as patients

    await use_tenant(session, tenant_id)   # เผื่อเทสสลับ tenant มาก่อนหน้า
    admin = scope_for(tenant_id, "user-1")
    patient = await patients.create_patient(
        session,
        admin,
        display_name="คุณยาย",
        timezone=timezone,
        care_profile=profile or {"routine": True, "medication": True, "caregiver_escalation": True},
        channels=["line"],
        quiet_hours=quiet_hours,
    )
    await tenancy.grant_consent(
        session,
        admin,
        subject_id=patient.patient_id,
        grantee=tenancy.Principal(type="human", id="user-1"),
        scopes=["care.manage"],
        granted_by=tenancy.Principal(type="human", id="user-1"),
            authority_basis="ผู้ดูแลหลักที่ครอบครัวมอบหมาย",
    )
    await tenancy.grant_consent(
        session,
        admin,
        subject_id=patient.patient_id,
        grantee=tenancy.Principal(type="service", id="care-orchestrator"),
        scopes=["care.manage"],
        granted_by=tenancy.Principal(type="human", id="user-1"),
            authority_basis="ผู้ดูแลหลักที่ครอบครัวมอบหมาย",
    )
    caregiver = None
    if with_caregiver:
        caregiver = await patients.add_caregiver(
            session,
            admin,
            principal_id="user-2",
            display_name="ลูกสาว",
            relation="daughter",
            channel="line",
        )
        await patients.assign_to_care_team(
            session, admin, patient_id=patient.patient_id, caregiver_id=caregiver.caregiver_id
        )
        await tenancy.grant_consent(
            session,
            admin,
            subject_id=patient.patient_id,
            grantee=tenancy.Principal(type="human", id="user-2"),
            scopes=["routine.read", "medication.read"],
            granted_by=tenancy.Principal(type="human", id="user-1"),
            authority_basis="ผู้ดูแลหลักที่ครอบครัวมอบหมาย",
        )
    await session.commit()
    return patient, caregiver


async def notifications(session, tenant_id: str, patient_id: str, audience: str | None = None):
    """ข้อความที่ส่งออกจริงของผู้ป่วยรายนี้ — กรอง tenant เสมอ

    เทสห้าม `select(CareNotification)` ลอย ๆ เพราะจะไปเห็นของเทสอื่นที่รันก่อนหน้า
    (เป็นเหตุผลเดียวกับที่โค้ดจริงต้องผ่าน tenant guard เสมอ)
    """
    from sqlalchemy import select

    from care_addons.ap_tenancy.services import scoped
    from care_addons.care_escalation.models import CareNotification

    stmt = select(CareNotification).where(CareNotification.patient_id == patient_id)
    if audience:
        stmt = stmt.where(CareNotification.audience == audience)
    result = await session.execute(
        scoped(stmt.order_by(CareNotification.sent_at), CareNotification, scope_for(tenant_id))
    )
    return list(result.scalars())


async def audit_events(session, tenant_id: str, patient_id: str | None = None):
    from sqlalchemy import select

    from care_addons.ap_audit.models import ApAuditEvent

    stmt = select(ApAuditEvent).where(ApAuditEvent.tenant_id == tenant_id)
    result = await session.execute(stmt.order_by(ApAuditEvent.occurred_at))
    events = list(result.scalars())
    if patient_id:
        events = [e for e in events if (e.attributes or {}).get("patient_id") == patient_id]
    return events
