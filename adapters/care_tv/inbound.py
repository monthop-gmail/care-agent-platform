"""ขาเข้า — สามทาง และไม่มีทางไหนเป็นของใหม่

🔒 `mark_presented` **ไม่ใช่ evidence** และไม่ปิดงาน (ADR-0014 ข้อ 5)
   ทางเดียวที่ปิดงานได้คือ `acknowledge()` ที่มีคนกดจริง
"""

from __future__ import annotations

from adapters.care_tv.remote import DONE, HELP, NOT_YET, intent_for
from care_addons.care_escalation import services as jobs


async def presented(session, scope, notification_id: int):
    """วางบนจอแล้ว — ข้อเท็จจริงเกี่ยวกับช่องทาง ไม่ใช่เกี่ยวกับคน"""
    return await jobs.mark_presented(session, scope, notification_id)


async def key_pressed(session, scope, care_job_id: str, key: str) -> str:
    """ปุ่ม → เจตนา → เรียกของที่มีอยู่แล้วในโดเมน

    🔒 map แบบ deterministic · ปุ่มที่ไม่รู้จัก raise ไม่ใช่เดาเป็นเจตนาใด
    """
    intent = intent_for(key)
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
