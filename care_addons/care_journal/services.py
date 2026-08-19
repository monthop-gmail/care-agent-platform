"""Health journal — บันทึกสิ่งที่ผู้ป่วยสังเกตเห็นและคำถามที่อยากถามหมอ

ผู้ป่วยพูดธรรมดาได้ ไม่ต้องเลือกหมวด ไม่ต้องเลือกหมอ — `unclassified` เป็นสถานะที่ถูกต้อง
"""

from __future__ import annotations

from core.tenancy import Principal, TenantScope, new_id, scoped
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action
from care_addons.care_journal.models import CLASSIFICATIONS, ENTRY_TYPES, CareJournalEntry
from care_addons.care_patient.services import get_patient


@care_action("journal.entry.write")
async def record(
    session: AsyncSession,
    scope: TenantScope,
    *,
    patient_id: str,
    text: str,
    entry_type: str = "observation",
    target_specialty: str | None = None,
    classification: str = "unclassified",
    recorded_by: Principal | None = None,
) -> CareJournalEntry:
    if entry_type not in ENTRY_TYPES:
        raise ValueError(f"entry_type ไม่รู้จัก: {entry_type}")
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"classification ไม่รู้จัก: {classification}")
    if not text.strip():
        raise ValueError("บันทึกที่ไม่มีข้อความไม่มีความหมาย")
    await get_patient(session, scope, patient_id, required_scope="journal.read")

    entry = CareJournalEntry(
        entry_id=new_id("jrn"),
        tenant_id=scope.tenant_id,
        patient_id=patient_id,
        entry_type=entry_type,
        text=text,
        recorded_by=(recorded_by or scope.principal).as_dict(),
        classification=classification,
        target_specialty=target_specialty,
    )
    session.add(entry)
    await session.flush()
    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=entry.entry_id,
        care_event_type="care.question.recorded" if entry_type == "question" else "care.journal.recorded",
        severity="low",
        evidence={"kind": "patient_confirmed", "recorded_by": entry.recorded_by},
        transition={"from": None, "to": "open", "reason": entry_type},
        attributes={"record_type": "journal_entry", "patient_id": patient_id, "entry_type": entry_type},
    )
    return entry


async def open_questions(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, specialty: str | None = None
) -> list[CareJournalEntry]:
    """คำถามที่ยังไม่ได้ถามหมอ — ต้องถูกดึงมาแสดงก่อนวันนัดโดยอัตโนมัติ"""
    stmt = select(CareJournalEntry).where(
        CareJournalEntry.patient_id == patient_id,
        CareJournalEntry.entry_type == "question",
        CareJournalEntry.status == "open",
    )
    if specialty:
        stmt = stmt.where(
            (CareJournalEntry.target_specialty == specialty)
            | (CareJournalEntry.target_specialty.is_(None))
        )
    result = await session.execute(
        scoped(stmt.order_by(CareJournalEntry.recorded_at), CareJournalEntry, scope)
    )
    return list(result.scalars())


async def recent_entries(
    session: AsyncSession, scope: TenantScope, patient_id: str, *, limit: int = 50
) -> list[CareJournalEntry]:
    result = await session.execute(
        scoped(
            select(CareJournalEntry)
            .where(CareJournalEntry.patient_id == patient_id)
            .order_by(CareJournalEntry.recorded_at.desc())
            .limit(limit),
            CareJournalEntry,
            scope,
        )
    )
    return list(result.scalars())


async def visit_brief(session: AsyncSession, scope: TenantScope, patient_id: str, *, specialty: str | None = None) -> dict:
    """สิ่งที่ควรแจ้ง/ถามคุณหมอ — 🔒 สร้างจากสิ่งที่บันทึกไว้จริงเท่านั้น ห้ามเติมเนื้อหาเอง"""
    await get_patient(session, scope, patient_id, required_scope="journal.read")
    entries = await recent_entries(session, scope, patient_id)
    questions = await open_questions(session, scope, patient_id, specialty=specialty)
    observations = [e for e in entries if e.entry_type in ("observation", "side_effect", "concern")]
    return {
        "patient_id": patient_id,
        "specialty": specialty,
        "observations": [
            {"text": e.text, "recorded_at": e.recorded_at.isoformat(), "type": e.entry_type}
            for e in observations
        ],
        "questions": [{"entry_id": e.entry_id, "text": e.text} for e in questions],
        "note": "สร้างจากบันทึกที่มีอยู่จริงเท่านั้น — ไม่มีการตีความทางการแพทย์",
    }
