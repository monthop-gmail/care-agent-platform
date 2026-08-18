"""สร้างข้อมูลตัวอย่างสำหรับ demo — หนึ่งวันของผู้ป่วยหนึ่งคน

    python examples/seed_demo.py

ต้องตั้ง PSTACK_* ให้ชี้ DB ที่ต้องการก่อน (ดู .env.example) — สคริปต์นี้ไม่แตะ production
scenario ตาม blueprint §20: 07:30 อาหารเช้า · 08:00 ยา · 12:00 อาหารกลางวัน · 20:00 ยา
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = "t-demo-family"
ADMIN = "user-1"

ROUTINES = [
    ("wake", "ตื่นนอน", "06:45", "low"),
    ("meal", "อาหารเช้า", "07:30", "medium"),
    ("medication", "ยาเช้า หลังอาหาร", "08:00", "medium"),
    ("activity", "เดินออกกำลังกาย 20 นาที", "10:00", "low"),
    ("meal", "อาหารกลางวัน", "12:00", "medium"),
    ("meal", "อาหารเย็น", "17:30", "medium"),
    ("medication", "ยาก่อนนอน", "20:00", "medium"),
    ("sleep", "เข้านอน", "21:00", "low"),
]


async def main() -> None:
    from core.db import dispose_engine, get_sessionmaker

    from care_addons.ap_tenancy import services as tenancy
    from care_addons.care_journal import services as journal
    from care_addons.care_medication import services as meds
    from care_addons.care_patient import services as patients
    from care_addons.care_routine import services as routines

    scope = tenancy.TenantScope(
        tenant_id=TENANT,
        principal=tenancy.Principal(type="human", id=ADMIN, display_name="ผู้ดูแลระบบ"),
    )

    async with get_sessionmaker()() as session:
        await tenancy.create_tenant(session, TENANT, "ครอบครัวตัวอย่าง")
        patient = await patients.create_patient(
            session,
            scope,
            display_name="คุณยายสมศรี",
            care_profile={
                "routine": True,
                "medication": True,
                "appointment": True,
                "memory_assistance": True,
                "caregiver_escalation": True,
            },
            channels=["line"],
            quiet_hours=("21:30", "06:00"),
        )
        for grantee in (ADMIN, "care-orchestrator"):
            await tenancy.grant_consent(
                session,
                scope,
                subject_id=patient.patient_id,
                grantee=tenancy.Principal(
                    type="service" if grantee == "care-orchestrator" else "human", id=grantee
                ),
                scopes=["care.manage"],
                granted_by=tenancy.Principal(type="human", id=ADMIN),
            )

        daughter = await patients.add_caregiver(
            session, scope, principal_id="user-2", display_name="คุณลูกสาว", relation="daughter", channel="line"
        )
        await patients.assign_to_care_team(
            session, scope, patient_id=patient.patient_id, caregiver_id=daughter.caregiver_id
        )
        await tenancy.grant_consent(
            session,
            scope,
            subject_id=patient.patient_id,
            grantee=tenancy.Principal(type="human", id="user-2"),
            scopes=["routine.read", "meal.read", "medication.read"],
            granted_by=tenancy.Principal(type="human", id=ADMIN),
        )

        for kind, label, at, severity in ROUTINES:
            await routines.add_routine(
                session,
                scope,
                patient_id=patient.patient_id,
                kind=kind,
                label=label,
                scheduled_time=at,
                severity=severity,
            )

        # ยาหนึ่งตัวที่ผ่านการยืนยันของคนแล้ว (AI สร้างเองไม่ได้ — ADR-0006)
        proposed = await meds.propose_version(
            session,
            scope,
            patient_id=patient.patient_id,
            name="Donepezil 5mg",
            schedule=[{"time": "20:00", "relation_to_meal": "bedtime", "dose": "1 เม็ด"}],
            instruction_source="doctor_instruction",
            prescribed_by={"doctor_name": "นพ.สมชาย", "specialty": "neurology"},
        )
        await meds.confirm_version(
            session,
            scope,
            proposed.version_id,
            confirmed_by=tenancy.Principal(type="human", id="user-2", display_name="คุณลูกสาว"),
        )

        await journal.record(
            session,
            scope,
            patient_id=patient.patient_id,
            text="ช่วงนี้เดินแล้วรู้สึกเวียนหัว",
            entry_type="observation",
        )
        await journal.record(
            session,
            scope,
            patient_id=patient.patient_id,
            text="ยาตัวนี้ทำให้ง่วงหรือไม่?",
            entry_type="question",
            target_specialty="neurology",
        )

        created = await routines.materialize_day(session, scope, patient.patient_id)
        await session.commit()

        print(f"tenant       : {TENANT}")
        print(f"patient      : {patient.patient_id} ({patient.display_name})")
        print(f"routines     : {len(ROUTINES)}")
        print(f"jobs วันนี้   : {len(created)}")
        print("\nลองต่อ:")
        print(f"  curl -H 'X-Tenant-Id: {TENANT}' localhost:8000/api/care/routines/today?patient_id={patient.patient_id}")
        print(f"  curl -X POST -H 'X-Tenant-Id: {TENANT}' localhost:8000/api/care/jobs/tick")

    await dispose_engine()


if __name__ == "__main__":
    os.environ.setdefault("PSTACK_ADDONS_PATHS", "../pstack/addons,care_addons")
    asyncio.run(main())
