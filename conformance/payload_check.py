#!/usr/bin/env python3
"""Conformance test ระดับ payload — เงื่อนไขข้อ 2 ของการเป็น consumer ตาม agent-platform ADR-0006

ต่างจาก `drift_check.py` ที่ตรวจว่า **contract ของเรา** ยัง `$ref` ถูกที่
ตัวนี้รัน scenario จริงแล้วเอา **payload ที่ระบบผลิตออกมาจริง** ไป validate กับ JSON Schema
ของ agent-platform ที่ commit ที่ pin ไว้ — ตอบคำถามว่า "เราทำตาม contract จริงหรือแค่บอกว่าทำ"

    python conformance/payload_check.py            # ต้องต่อเน็ตครั้งแรกเพื่อดึง schema (แล้ว cache)
    python conformance/payload_check.py --offline  # ใช้ cache เดิม ไม่ต่อเน็ต
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys
import urllib.request
from datetime import timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for candidate in (ROOT / "pstack_src", ROOT.parent / "pstack"):
    if (candidate / "addons").is_dir():
        os.environ.setdefault("PSTACK_ADDONS_PATHS", f"{candidate / 'addons'},care_addons")
        sys.path.insert(0, str(candidate))
        break

CHECK_DB = ROOT / "payload_check.db"
CACHE = ROOT / ".schema_cache"
PINNED = ROOT / "conformance" / "pinned.yaml"
RAW = "https://raw.githubusercontent.com/{repo}/{commit}/contracts/{path}"
PLATFORM_HOST = "https://schemas.agent-platform.internal/"

os.environ.setdefault("PSTACK_DATABASE_URL", f"sqlite+aiosqlite:///{CHECK_DB}")
os.environ.setdefault("PSTACK_SECRET_KEY", "payload-check")
os.environ.setdefault(
    "PSTACK_MODULES",
    "users,tenancy,ap_consent,ap_tenancy,ap_audit,ap_policy,ap_approval,care_patient,care_escalation,care_routine,"
    "care_medication,care_journal,care_appointment,care_orientation,care_orchestrator",
)

# schema ที่ต้องมีใน registry เพื่อ resolve $ref ระหว่างไฟล์
SCHEMA_FILES = [
    "identity/v1/identity.schema.yaml",
    "event/v1/event.schema.yaml",
    "policy/v1/policy-decision.schema.yaml",
    "capability/v1/capability.schema.yaml",
    "error/v1/error.schema.yaml",
    "model/v1/inference.schema.yaml",
    "consent/v1/consent.schema.yaml",
    "approval/v1/approval.schema.yaml",
]

# attribute ของโดเมนที่ care-event.schema.yaml บังคับให้อยู่ระดับบนสุด
LIFT = ("patient_id",)


def load_pinned() -> dict:
    import yaml

    return yaml.safe_load(PINNED.read_text(encoding="utf-8"))


def fetch_schemas(pinned: dict, *, offline: bool) -> dict[str, dict]:
    import yaml

    repo, commit = pinned["repo"], pinned["commit"]
    CACHE.mkdir(exist_ok=True)
    schemas: dict[str, dict] = {}
    for path in SCHEMA_FILES:
        cached = CACHE / f"{commit[:8]}-{path.replace('/', '_')}"
        if not cached.exists():
            if offline:
                raise SystemExit(f"✗ ไม่มี cache ของ {path} — รันโดยไม่ใส่ --offline หนึ่งครั้งก่อน")
            url = RAW.format(repo=repo, commit=commit, path=path)
            with urllib.request.urlopen(url, timeout=30) as response:
                cached.write_bytes(response.read())
        document = yaml.safe_load(cached.read_text(encoding="utf-8"))
        schemas[document["$id"]] = document
    return schemas


def build_validator(schemas: dict[str, dict], schema: dict):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    registry = Registry().with_resources(
        [(uri, Resource.from_contents(doc)) for uri, doc in schemas.items()]
    )
    return Draft202012Validator(schema, registry=registry)


def care_event_schema(schemas: dict[str, dict]) -> dict:
    """care-event.schema.yaml ของเรา — ตัด key ที่ไม่ใช่ JSON Schema ออก"""
    import yaml

    document = yaml.safe_load(
        (ROOT / "contracts" / "event" / "v1" / "care-event.schema.yaml").read_text(encoding="utf-8")
    )
    for key in ("extends", "care_rules", "description", "title"):
        document.pop(key, None)
    return document


async def run_scenario() -> tuple[list, list, list]:
    """เดินสถานการณ์จริงหนึ่งวันของผู้ป่วยหนึ่งคน

    คืน (audit events, policy decisions, consent grants)
    """
    from core.app import create_app  # core.app เรียก logging.basicConfig ตอน import
    from core.db import dispose_engine, get_engine, get_sessionmaker
    from core.registry import create_core_tables, sync_modules
    from core.runtime import ctx
    from core.tenancy import bind_tenant
    from sqlalchemy import select

    from care_addons.ap_approval import services as approvals
    from care_addons.ap_approval.models import ApApproval
    from care_addons.ap_audit.models import ApAuditEvent
    from care_addons.ap_consent.models import ApConsentGrant
    from care_addons.ap_policy.engine import evaluate
    from care_addons.ap_tenancy import services as tenancy
    from care_addons.ap_tenancy.clock import FakeClock
    from care_addons.care_appointment import services as appointments
    from care_addons.care_escalation import services as jobs
    from care_addons.care_journal import services as journal
    from care_addons.care_medication import services as medications
    from care_addons.care_orientation import services as orientation
    from care_addons.care_patient import services as patients
    from care_addons.care_routine import services as routines

    logging.getLogger().setLevel(
        logging.INFO if os.environ.get("PAYLOAD_CHECK_VERBOSE") else logging.WARNING
    )

    url = os.environ["PSTACK_DATABASE_URL"]
    if url.startswith("sqlite"):
        CHECK_DB.unlink(missing_ok=True)

    create_app()
    engine = get_engine()
    if not url.startswith("sqlite"):
        from sqlalchemy import text

        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    await create_core_tables(engine)
    async with get_sessionmaker()() as bootstrap:
        await sync_modules(engine, bootstrap, ctx.load_order)

    tenant_id = "t-payload-check"
    admin = tenancy.TenantScope(
        tenant_id=tenant_id,
        principal=tenancy.Principal(type="human", id="user-1", display_name="ผู้ดูแลระบบ"),
    )
    system = tenancy.TenantScope(
        tenant_id=tenant_id, principal=tenancy.Principal(type="service", id="care-orchestrator")
    )

    with FakeClock("2026-08-19T00:30:00+00:00") as clock:
        async with get_sessionmaker()() as session:
            await tenancy.create_tenant(session, tenant_id, "ครอบครัวตรวจสอบ")
            await bind_tenant(session, tenant_id)   # RLS ของตารางโดเมน
            patient = await patients.create_patient(
                session,
                admin,
                display_name="คุณยาย",
                care_profile={
                    "routine": True, "medication": True, "appointment": True,
                    "memory_assistance": True, "caregiver_escalation": True,
                },
                channels=["line"],
            )
            for grantee, kind in (("user-1", "human"), ("care-orchestrator", "service")):
                await tenancy.grant_consent(
                    session, admin,
                    subject_id=patient.patient_id,
                    grantee=tenancy.Principal(type=kind, id=grantee),
                    scopes=["care.manage"],
                    granted_by=tenancy.Principal(type="human", id="user-1"),
                    authority_basis="ผู้ดูแลหลักที่ครอบครัวมอบหมาย",
                )
            # ใบที่ถูกเพิกถอน — ให้ payload ที่มี revoked_* ครบเข้าไป validate ด้วย
            revoked = await tenancy.grant_consent(
                session, admin,
                subject_id=patient.patient_id,
                grantee=tenancy.Principal(type="human", id="user-9"),
                scopes=["routine.read"],
                purpose="family_awareness",
                granted_by=tenancy.Principal(type="human", id="user-1"),
                authority_basis="ผู้ดูแลหลักที่ครอบครัวมอบหมาย",
            )
            await tenancy.revoke_consent(
                session, admin, revoked.grant_id, reason="ญาติย้ายออกจากทีมดูแลแล้ว"
            )
            caregiver = await patients.add_caregiver(
                session, admin, principal_id="user-2", display_name="ลูกสาว", relation="daughter"
            )
            await patients.assign_to_care_team(
                session, admin, patient_id=patient.patient_id, caregiver_id=caregiver.caregiver_id
            )
            await routines.add_routine(
                session, admin, patient_id=patient.patient_id, kind="medication",
                label="ยาเช้า หลังอาหาร", scheduled_time="08:00",
            )
            await routines.add_routine(
                session, admin, patient_id=patient.patient_id, kind="meal",
                label="อาหารเช้า", scheduled_time="07:30",
            )
            await journal.record(
                session, admin, patient_id=patient.patient_id,
                text="ช่วงนี้เดินแล้วรู้สึกเวียนหัว",
            )
            await journal.record(
                session, admin, patient_id=patient.patient_id,
                text="ยาตัวนี้ทำให้ง่วงหรือไม่?", entry_type="question",
                target_specialty="neurology",
            )

            # ยาที่ขัดกันจากหมองสองคน → conflict (GOVERNANCE_DECISION + care.medication.conflict)
            for dose, doctor in (("1 เม็ด", "หมอ A"), ("ครึ่งเม็ด", "หมอ B")):
                version = await medications.propose_version(
                    session, admin, patient_id=patient.patient_id, name="Med X",
                    schedule=[{"time": "08:00", "relation_to_meal": "after_meal", "dose": dose}],
                    instruction_source="doctor_instruction",
                    prescribed_by={"doctor_name": doctor},
                )
                await medications.confirm_version(
                    session, admin, version.version_id,
                    confirmed_by=tenancy.Principal(type="human", id="user-1"),
                )

            # agent เสนอยาอีกตัว แล้วคนกดอนุมัติ → ได้ใบอนุมัติจริงตาม approval/v1
            agent_scope = tenancy.TenantScope(
                tenant_id=tenant_id,
                principal=tenancy.Principal(type="agent", id="care-agent"),
            )
            await tenancy.grant_consent(
                session, admin, subject_id=patient.patient_id,
                grantee=tenancy.Principal(type="agent", id="care-agent"),
                scopes=["care.manage"],
                granted_by=tenancy.Principal(type="human", id="user-1"),
                authority_basis="ผู้ดูแลหลักมอบหมาย",
            )
            await medications.propose_version(
                session, agent_scope, patient_id=patient.patient_id, name="Med Y",
                schedule=[{"time": "20:00", "relation_to_meal": "bedtime", "dose": "1 เม็ด"}],
                instruction_source="doctor_instruction",
                prescribed_by={"doctor_name": "หมอ C"},
            )
            for request in await approvals.pending_requests(session, admin):
                await approvals.decide(
                    session, admin, request_id=request.request_id,
                    decision="APPROVE", reason="ยืนยันตามที่หมอสั่งแล้ว",
                    authority={"type": "human", "id": "user-2", "display_name": "ลูกสาว"},
                )

            appointment = await appointments.create_appointment(
                session, admin, patient_id=patient.patient_id,
                starts_at=clock.set("2026-08-19T00:30:00+00:00") + timedelta(days=1),
                doctor_name="สมชาย", specialty="neurology", purpose="ตรวจเลือด",
            )
            await appointments.schedule_reminders(session, admin, appointment.appointment_id)
            await appointments.build_default_plan(session, admin, appointment.appointment_id)
            await orientation.daily_brief(session, admin, patient.patient_id)
            await routines.materialize_day(session, system, patient.patient_id)
            await session.commit()

        # เดินวงจร: เตือน → เงียบ → เตือนซ้ำ → พลาด → ส่งต่อผู้ดูแล
        clock.set("2026-08-19T01:00:00+00:00")
        async with get_sessionmaker()() as session:
            await bind_tenant(session, tenant_id)
            for _ in range(5):
                await jobs.run_due_jobs(session, system)
                await session.commit()
                clock.advance(minutes=25)

            open_ones = await jobs.open_jobs(session, system, patient.patient_id)
            if open_ones:
                await jobs.acknowledge(
                    session,
                    tenancy.TenantScope(
                        tenant_id=tenant_id,
                        principal=tenancy.Principal(type="human", id=patient.patient_id),
                    ),
                    open_ones[0].care_job_id,
                )
            await session.commit()

        async with get_sessionmaker()() as session:
            await bind_tenant(session, tenant_id)
            rows = (
                await session.execute(select(ApAuditEvent).order_by(ApAuditEvent.occurred_at))
            ).scalars()
            events = list(rows)
            grants = list(
                (await session.execute(select(ApConsentGrant))).scalars()
            )
            approval_rows = list((await session.execute(select(ApApproval))).scalars())

    decisions = [
        evaluate(capability)
        for capability in (
            "routine.reminder.send", "medication.regimen.write",
            "caregiver.notify", "emergency.escalate",
        )
    ]
    await dispose_engine()
    if url.startswith("sqlite"):
        CHECK_DB.unlink(missing_ok=True)
    return events, decisions, grants, approval_rows


def main() -> int:
    offline = "--offline" in sys.argv
    logging.getLogger().setLevel(logging.WARNING)

    pinned = load_pinned()
    schemas = fetch_schemas(pinned, offline=offline)

    from care_addons.ap_approval.services import as_approval
    from care_addons.ap_audit.services import as_platform_event
    from care_addons.ap_consent.services import as_consent_grant

    events, decisions, grants, approvals_made = asyncio.run(run_scenario())
    if not events:
        print("✗ scenario ไม่ได้ผลิต event เลย — เช็คว่า scenario ยังทำงานอยู่")
        return 1

    event_validator = build_validator(schemas, schemas[f"{PLATFORM_HOST}event/v1/event.schema.yaml"])
    care_validator = build_validator(schemas, care_event_schema(schemas))
    # `Decision` เป็น sub-schema ในไฟล์ policy — ต้องพก $defs + $id ของไฟล์ไปด้วย
    # ไม่งั้น $ref แบบ `#/$defs/Effect` จะ resolve ไม่เจอ
    policy_document = schemas[f"{PLATFORM_HOST}policy/v1/policy-decision.schema.yaml"]
    decision_validator = build_validator(
        schemas,
        {
            "$id": policy_document["$id"],
            "$defs": policy_document["$defs"],
            **policy_document["Decision"],
        },
    )

    failures: list[str] = []
    care_count = 0
    for event in events:
        payload = as_platform_event(event, lift=LIFT)
        for error in event_validator.iter_errors(payload):
            failures.append(
                f"event/v1 · {event.event_type} ({event.event_id}): "
                f"{error.json_path} — {error.message}"
            )
        if payload.get("care_event_type"):
            care_count += 1
            for error in care_validator.iter_errors(payload):
                failures.append(
                    f"care-event/v1 · {payload['care_event_type']} ({event.event_id}): "
                    f"{error.json_path} — {error.message}"
                )

    consent_validator = build_validator(
        schemas, schemas[f"{PLATFORM_HOST}consent/v1/consent.schema.yaml"]
    )
    for grant in grants:
        payload = as_consent_grant(grant)
        for error in consent_validator.iter_errors(payload):
            failures.append(
                f"consent/v1 · {grant.grant_id}: {error.json_path} — {error.message}"
            )

    approval_validator = build_validator(
        schemas, schemas[f"{PLATFORM_HOST}approval/v1/approval.schema.yaml"]
    )
    for row in approvals_made:
        payload = as_approval(row)
        for error in approval_validator.iter_errors(payload):
            failures.append(
                f"approval/v1 · {row.decision} ({row.approval_id}): "
                f"{error.json_path} — {error.message}"
            )

    for decision in decisions:
        payload = {
            **decision.as_policy_result(),
            "evaluated_at": decision.evaluated_at.isoformat(),
            "reason": decision.reason,
            "constraint": decision.constraint,
        }
        for error in decision_validator.iter_errors(payload):
            failures.append(f"policy/v1 Decision · {decision.capability}: {error.message}")

    for failure in failures[:30]:
        print(f"   {failure}")
    if failures:
        print(f"\n✗ payload conformance ไม่ผ่าน — {len(failures)} ข้อ จาก {len(events)} event")
        return 1

    print(
        f"✓ payload conformance ผ่าน — {len(events)} audit event (care event {care_count}) "
        f"+ {len(grants)} consent grant + {len(approvals_made)} approval "
        f"+ {len(decisions)} policy decision "
        f"validate กับ agent-platform @ {pinned['commit'][:8]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
