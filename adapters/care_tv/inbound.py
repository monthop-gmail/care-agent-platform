"""ขาเข้า — สามทาง และไม่มีทางไหนเป็นของใหม่

🔒 `mark_presented` **ไม่ใช่ evidence** และไม่ปิดงาน (ADR-0014 ข้อ 5)
   ทางเดียวที่ปิดงานได้คือ `acknowledge()` ที่มีคนกดจริง
"""

from __future__ import annotations

from adapters.care_tv.prompts import PromptBook, StalePrompt
from adapters.care_tv.remote import DONE, HELP, NOT_YET, intent_for
from care_addons.care_escalation import services as jobs


async def presented(session, scope, notification_id: int):
    """วางบนจอแล้ว — ข้อเท็จจริงเกี่ยวกับช่องทาง ไม่ใช่เกี่ยวกับคน"""
    return await jobs.mark_presented(session, scope, notification_id)


async def key_pressed(
    session,
    scope,
    care_job_id: str,
    key: str,
    *,
    prompts: PromptBook | None = None,
    at: float | None = None,
) -> str:
    """ปุ่ม → เจตนา → เรียกของที่มีอยู่แล้วในโดเมน

    🔒 map แบบ deterministic · ปุ่มที่ไม่รู้จัก raise ไม่ใช่เดาเป็นเจตนาใด

    🔒 ถ้าส่ง `prompts` มา การกดตอบคำถามที่ **หมดอายุแล้ว** จะถูกปฏิเสธก่อนถึงโดเมน
       เพราะการกด "ทำแล้ว" ของคำเตือนเมื่อเช้า จะกลายเป็นหลักฐานว่ากินยารอบนั้นแล้ว
       ทั้งที่รอบนั้นปิดไปแล้ว · ขอความช่วยเหลือ (`HELP`) ไม่ถูกกั้น ดูเหตุผลข้างล่าง
    """
    intent = intent_for(key)
    if (
        prompts is not None
        and intent in (DONE, NOT_YET)
        and not prompts.is_fresh(care_job_id, at=at)
    ):
        # 🔒 `HELP` ไม่เคยถูกกั้นด้วยความสด — คนกดขอความช่วยเหลือคือเหตุการณ์ของ
        #    **ตอนนี้** ไม่ใช่คำตอบของงานเมื่อเช้า · การปฏิเสธมันคือการเงียบ
        raise StalePrompt(
            f"คำถามของงาน {care_job_id} หมดอายุแล้ว — การกดตอบต้องไม่กลายเป็นหลักฐาน"
        )
    if intent == DONE:
        await jobs.acknowledge(
            session, scope, care_job_id, evidence_kind="patient_confirmed", done=True
        )
    elif intent == NOT_YET:
        await jobs.acknowledge(
            session, scope, care_job_id, evidence_kind="patient_confirmed", done=False
        )
    elif intent == HELP:
        await jobs.escalate(session, scope, await jobs.get_job(session, scope, care_job_id))
    return intent
