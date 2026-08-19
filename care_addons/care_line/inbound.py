"""รับข้อความจากผู้ป่วย/ผู้ดูแลใน LINE แล้วตอบแบบ deterministic

🔒 **ไม่ส่งต่อให้ LLM โดยอัตโนมัติ** (ADR-0008) — ข้อความที่ระบบไม่เข้าใจจะได้คำตอบว่า
   "ยังไม่เข้าใจ" พร้อมตัวอย่างสิ่งที่พูดได้ ไม่ใช่คำตอบที่ฟังดูดีแต่เดามา
   เพราะผู้ใช้กลุ่มนี้แยกไม่ออกว่าอันไหนคือข้อมูลจริง อันไหนคือ AI เดา

🔒 ไม่มีหลักฐาน = ตอบว่าไม่มีข้อมูล ห้ามอนุมานจากเวลาที่ผ่านไป (ADR-0006 ข้อ 5)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.runtime import ctx
from core.tenancy import Principal, TenantScope, bind_tenant
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.care_escalation import services as jobs
from care_addons.care_line import services as line
from care_addons.care_line.models import CareLineBinding

logger = logging.getLogger(__name__)

PAIR_PREFIXES = ("ผูก", "จับคู่", "care", "pair")
CONFIRM_WORDS = (
    "ทำแล้ว", "กินแล้ว", "ทานแล้ว", "ทานยาแล้ว", "กินยาแล้ว", "เรียบร้อย",
    "เสร็จแล้ว", "เรียบร้อยแล้ว", "ทำเรียบร้อย", "ok", "โอเค",
)
NOT_YET_WORDS = ("ยังไม่ได้", "ยังไม่", "ยัง", "ไม่ได้ทำ")
DATE_WORDS = ("วันนี้วันอะไร", "วันอะไร", "วันที่เท่าไร", "วันที่เท่าไหร่", "กี่โมง", "เวลาเท่าไร")
JOURNAL_PREFIXES = ("จด", "บันทึก")
MEDICATION_QUESTION = ("กินยาแล้วยัง", "ทานยาแล้วยัง", "กินยารึยัง", "ทานยารึยัง")
MEDICATION_LIST = ("ยาอะไรบ้าง", "วันนี้กินยาอะไร", "ยาวันนี้", "ต้องกินยาอะไร")
PLAN_WORDS = {
    "วันนี้ต้องทำอะไร": "วันนี้", "วันนี้มีอะไร": "วันนี้", "วันนี้ทำอะไร": "วันนี้",
    "พรุ่งนี้ต้องทำอะไร": "พรุ่งนี้", "พรุ่งนี้มีอะไร": "พรุ่งนี้", "พรุ่งนี้ทำอะไร": "พรุ่งนี้",
}
CAREGIVER_ACK = ("รับเรื่อง", "รับทราบ", "ดูแลแล้ว", "จัดการแล้ว")

HELP_TEXT = (
    "ผมยังไม่เข้าใจข้อความนี้ครับ 🙏\n"
    "ลองพูดแบบนี้ได้เลย:\n"
    "• “ทำแล้ว” หรือ “ยัง” — ตอบรายการที่ผมเพิ่งเตือน\n"
    "• “วันนี้วันอะไร”\n"
    "• “วันนี้ต้องทำอะไร” / “พรุ่งนี้ต้องทำอะไร”\n"
    "• “วันนี้กินยาอะไร”\n"
    "• “จด ...” เพื่อให้ผมบันทึกอาการหรือคำถามที่อยากถามคุณหมอ"
)

NO_OPEN_JOB = "ตอนนี้ไม่มีรายการที่รอการยืนยันครับ"


@dataclass(frozen=True)
class Intent:
    kind: str
    argument: str = ""


def interpret(text: str) -> Intent:
    """แปลงข้อความเป็นเจตนา — ฟังก์ชันบริสุทธิ์ ทดสอบแยกได้ ไม่มี LLM"""
    raw = text.strip()
    lowered = raw.lower()

    for prefix in PAIR_PREFIXES:
        if lowered.startswith(f"{prefix} "):
            return Intent("pair", raw.split(maxsplit=1)[1].strip())

    for prefix in JOURNAL_PREFIXES:
        if raw.startswith(prefix) and len(raw) > len(prefix) + 1:
            return Intent("journal", raw[len(prefix) :].strip(" :·-"))

    compact = raw.replace(" ", "")
    if any(word in compact for word in MEDICATION_QUESTION):
        return Intent("medication_status")
    if any(word in compact for word in MEDICATION_LIST):
        return Intent("medication_list")
    for phrase, expression in PLAN_WORDS.items():
        if phrase in compact:
            return Intent("plan", expression)
    if any(word in compact for word in DATE_WORDS):
        return Intent("date")
    if any(word in compact for word in CAREGIVER_ACK):
        return Intent("caregiver_ack")

    # ตรวจ "ยัง" ก่อน "ทำแล้ว" เพราะ "ยังไม่ได้ทำ" มีคำว่า "ทำ" อยู่ด้วย
    if any(compact.startswith(word) or compact == word for word in NOT_YET_WORDS):
        return Intent("not_yet")
    if any(word in compact for word in CONFIRM_WORDS):
        return Intent("confirm")

    return Intent("unknown")


def _scope(binding: CareLineBinding) -> TenantScope:
    """principal คือคนที่พิมพ์เข้ามาจริง ๆ — audit trail จึงชี้ตัวได้ถูก"""
    return TenantScope(
        tenant_id=binding.tenant_id,
        principal=Principal(
            type="human", id=binding.principal_id, display_name=binding.display_name
        ),
    )


async def _latest_open_job(session: AsyncSession, binding: CareLineBinding):
    scope = _scope(binding)
    open_states = ["reminded", "pending", "missed", "escalated"]
    candidates = await jobs.open_jobs(session, scope, binding.patient_id, states=open_states)
    if not candidates:
        return None
    # เอาอันที่เพิ่งเตือนล่าสุด — คนตอบ "ทำแล้ว" หมายถึงสิ่งที่เพิ่งได้ยิน
    reminded = [j for j in candidates if j.state in ("reminded", "missed", "escalated")]
    pool = reminded or candidates
    return max(pool, key=lambda j: j.due_at)


async def handle_message(session: AsyncSession, binding: CareLineBinding, text: str) -> str:
    from care_addons.care_journal import services as journal
    from care_addons.care_medication import services as medications
    from care_addons.care_orientation import services as orientation

    intent = interpret(text)
    scope = _scope(binding)

    if intent.kind in ("confirm", "not_yet"):
        job = await _latest_open_job(session, binding)
        if job is None:
            return NO_OPEN_JOB
        if binding.role == "caregiver":
            await jobs.caregiver_acknowledge(session, scope, job.care_job_id)
            return f"รับทราบครับ — บันทึกว่าคุณดูแลเรื่อง “{job.label}” แล้ว"
        done = intent.kind == "confirm"
        await jobs.acknowledge(session, scope, job.care_job_id, done=done)
        if done:
            return f"บันทึกแล้วครับว่า “{job.label}” เรียบร้อย ✅"
        return f"ไม่เป็นไรครับ เดี๋ยวผมเตือน “{job.label}” อีกครั้งนะครับ"

    if intent.kind == "caregiver_ack":
        job = await _latest_open_job(session, binding)
        if job is None:
            return NO_OPEN_JOB
        await jobs.caregiver_acknowledge(session, scope, job.care_job_id)
        return f"รับทราบครับ — หยุดเตือนเรื่อง “{job.label}” แล้ว"

    if intent.kind == "date":
        answer = await orientation.answer_date(session, scope, binding.patient_id)
        return answer["answer"]

    if intent.kind == "plan":
        result = await orientation.what_happens_on(
            session, scope, binding.patient_id, intent.argument
        )
        if not result["has_data"]:
            return f"{result['date_answer']} — {result['answer']}"
        lines = [f"{result['date_answer']} มีรายการนี้ครับ"]
        for appointment in result["appointments"]:
            who = f"คุณหมอ{appointment['doctor_name']}" if appointment["doctor_name"] else "คุณหมอ"
            lines.append(f"• {appointment['time']} น. นัด{who}")
        for item in result["plan"]:
            mark = "✅" if item["confirmed"] else "•"
            lines.append(f"{mark} {item['time']} น. {item['label']}")
        return "\n".join(lines)

    if intent.kind == "medication_list":
        versions = await medications.current_regimen(session, scope, binding.patient_id)
        if not versions:
            return "ตอนนี้ยังไม่มีรายการยาที่ยืนยันไว้ในระบบครับ"
        lines = ["ยาที่บันทึกไว้ตอนนี้ครับ"]
        for version in versions:
            if version.status == "needs_reconciliation":
                # 🔒 ยาที่คำสั่งขัดกันอยู่ ห้ามบอกจำนวนเม็ด (ADR-0005 ข้อ 4)
                lines.append(f"• {version.name} — รอผู้ดูแลตรวจสอบก่อนครับ")
                continue
            for entry in version.schedule or []:
                relation = {
                    "before_meal": "ก่อนอาหาร",
                    "after_meal": "หลังอาหาร",
                    "with_meal": "พร้อมอาหาร",
                    "empty_stomach": "ตอนท้องว่าง",
                    "bedtime": "ก่อนนอน",
                    "morning": "ตอนเช้า",
                    "as_needed": "เมื่อจำเป็น",
                    "specific_time": "ตามเวลา",
                }.get(entry.get("relation_to_meal", ""), "")
                lines.append(
                    f"• {entry.get('time', '')} น. {version.name} {entry.get('dose', '')} {relation}".rstrip()
                )
        return "\n".join(lines)

    if intent.kind == "medication_status":
        return await _medication_status(session, binding)

    if intent.kind == "journal":
        if not intent.argument:
            return "อยากให้ผมจดอะไรครับ? พิมพ์เช่น “จด ช่วงนี้เดินแล้วเวียนหัว” ได้เลย"
        entry_type = "question" if intent.argument.rstrip().endswith(("?", "ไหม", "หรือไม่")) else "observation"
        await journal.record(
            session,
            scope,
            patient_id=binding.patient_id,
            text=intent.argument,
            entry_type=entry_type,
        )
        if entry_type == "question":
            return "จดไว้ให้แล้วครับ ผมจะเอาไปเตือนตอนใกล้ถึงวันนัดคุณหมอ 📝"
        return "บันทึกไว้ให้แล้วครับ 📝 ต้องการเพิ่มรายละเอียดไหมครับ?"

    return HELP_TEXT


async def _medication_status(session: AsyncSession, binding: CareLineBinding) -> str:
    """"กินยาแล้วยัง" — ตอบจากหลักฐานเท่านั้น (scenario S7)"""
    scope = _scope(binding)
    todays = await jobs.open_jobs(session, scope, binding.patient_id)
    medication_jobs = [j for j in todays if j.source_kind == "medication"]
    if not medication_jobs:
        return "วันนี้ยังไม่มีรายการยาที่ผมติดตามอยู่ครับ"

    confirmed = [j for j in medication_jobs if j.state == "confirmed"]
    waiting = [j for j in medication_jobs if j.state not in ("confirmed", "cancelled")]

    lines = []
    for job in confirmed:
        stamp = job.closed_at or job.due_at
        lines.append(f"✅ {job.label} — บันทึกว่าทานแล้ว เวลา {stamp.strftime('%H:%M')} น.")
    for job in waiting:
        # 🔒 ไม่มีหลักฐาน = บอกว่าไม่มีข้อมูล ห้ามเดาว่าน่าจะทานแล้ว
        lines.append(f"❓ {job.label} — ยังไม่มีข้อมูลว่าทานแล้วครับ")
    if waiting:
        lines.append("\nถ้าจำไม่ได้ ลองดูที่กล่องยาหรือถามผู้ดูแลก่อนนะครับ")
    return "\n".join(lines)


@ctx.events.on("line.message.received")
async def on_line_message(payload: dict) -> None:
    """handler ที่ผูกกับ event ของ line_oa — ทำงานเมื่อ channel ตั้ง agent_enabled = false"""
    from core.db import get_sessionmaker

    channel_id = payload.get("channel", "")
    line_user_id = payload.get("line_user_id", "")
    text = (payload.get("text") or "").strip()
    # pstack >= v0.2.2 ส่ง reply_token มาด้วย — ตอบด้วย reply ที่ไม่นับโควตาแทน push
    reply_token = payload.get("reply_token")
    if not channel_id or not line_user_id or not text:
        return

    async with get_sessionmaker()() as session:
        # ตารางนี้เป็น "control plane ของช่องทาง" จึงไม่มี RLS — ต้องอ่านให้ได้ก่อน
        # ถึงจะรู้ว่า LINE user คนนี้เป็นของ tenant ไหน (เหตุผลเดียวกับที่ kernel
        # ไม่เปิด RLS บน tenant/tenant_member — ไม่งั้นหา scope ไม่ได้เลย)
        binding = await line.find_binding(
            session, channel_id=channel_id, line_user_id=line_user_id
        )
        if binding is not None:
            # รู้ tenant แล้ว — ตั้ง GUC ก่อนแตะข้อมูลโดเมนใด ๆ (care-agent-platform#4)
            await bind_tenant(session, binding.tenant_id)

        if binding is None:
            intent = interpret(text)
            if intent.kind != "pair":
                await line.transport(
                    channel_id,
                    line_user_id,
                    "สวัสดีครับ 🙏 บัญชีนี้ยังไม่ได้เชื่อมกับข้อมูลผู้ป่วย\n"
                    "ขอรหัสจับคู่จากผู้ดูแล แล้วพิมพ์ว่า “ผูก <รหัส>” ได้เลยครับ",
                    reply_token=reply_token,
                )
                return
            try:
                binding = await line.redeem_pairing_code(
                    session,
                    code=intent.argument,
                    channel_id=channel_id,
                    line_user_id=line_user_id,
                )
                await session.commit()
                await bind_tenant(session, binding.tenant_id)
            except line.PairingError as e:
                await line.transport(
                    channel_id,
                    line_user_id,
                    f"{e} — ขอรหัสใหม่จากผู้ดูแลได้ครับ",
                    reply_token=reply_token,
                )
                return
            await line.transport(
                channel_id,
                line_user_id,
                "เชื่อมบัญชีเรียบร้อยแล้วครับ ✅\nต่อไปผมจะคอยเตือนและตอบคำถามให้นะครับ",
                reply_token=reply_token,
            )
            return

        try:
            reply = await handle_message(session, binding, text)
            await session.commit()
        except Exception:
            logger.exception("จัดการข้อความจาก LINE ไม่สำเร็จ (patient=%s)", binding.patient_id)
            await session.rollback()
            reply = "ขออภัยครับ ระบบขัดข้องชั่วคราว ผมแจ้งผู้ดูแลให้แล้วนะครับ"

    await line.transport(channel_id, line_user_id, reply, reply_token=reply_token)
