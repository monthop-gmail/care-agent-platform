"""Orientation Agent — "สมองภายนอก" ชั้นแรกของผู้ป่วย

5 ชั้นตาม blueprint:
    1. TIME   ตอนนี้กี่โมง
    2. DATE   วันนี้วันอะไร
    3. PLACE  ตอนนี้อยู่ที่ไหน
    4. PERSON วันนี้จะพบใคร
    5. PLAN   วันนี้ต้องทำอะไร

🔒 กฎสองข้อที่ห้ามละเมิด:
   - **ถามซ้ำกี่ครั้งก็ตอบเหมือนเดิม** และห้ามมีถ้อยคำที่ทำให้ผู้ป่วยรู้สึกผิดที่ถามซ้ำ
   - **ไม่มีข้อมูล = บอกว่าไม่มีข้อมูล** ห้ามเดาจาก pattern หรือจากเวลาที่ผ่านไป (ADR-0006 ข้อ 5)

โมดูลนี้ไม่มีตารางของตัวเอง — มันประกอบคำตอบจากข้อมูลจริงของโมดูลอื่นเท่านั้น
ความจำของผู้ป่วยจึงไม่มีทาง "แตกต่างจากระบบ" เพราะไม่มีสำเนา
"""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from core.clock import now
from core.tenancy import TenantScope
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.services import care_action
from care_addons.care_appointment import services as appointments
from care_addons.care_medication import services as medications
from care_addons.care_patient.services import care_team, feature_enabled, get_patient
from care_addons.care_routine import services as routines

THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
THAI_MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]

# คำบอกเวลาแบบที่ผู้ป่วยพูดจริง → จำนวนวันจากวันนี้
RELATIVE_DAYS = {
    "วันนี้": 0, "today": 0,
    "พรุ่งนี้": 1, "tomorrow": 1,
    "เมื่อวาน": -1, "เมื่อวานนี้": -1, "yesterday": -1,
    "มะรืนนี้": 2,
}

NO_DATA = "ยังไม่มีข้อมูลครับ"


class UnknownTimeExpression(ValueError):
    """คำบอกเวลาที่ระบบไม่รู้จัก — ต้องถามผู้ใช้ ห้ามเดาว่าหมายถึงวันไหน"""


def thai_date(day: date) -> str:
    return f"วัน{THAI_DAYS[day.weekday()]}ที่ {day.day} {THAI_MONTHS[day.month - 1]}"


def resolve_day(expression: str, *, today: date) -> date:
    """แปลง "พรุ่งนี้" เป็นวันที่จริง — 🔒 resolve จากปฏิทิน ไม่ใช่ให้ LLM เดา"""
    key = expression.strip().lower()
    if key not in RELATIVE_DAYS:
        raise UnknownTimeExpression(
            f"ไม่รู้จักคำบอกเวลา {expression!r} — ต้องถามผู้ใช้ให้ชัด ห้ามเดา"
        )
    return today + timedelta(days=RELATIVE_DAYS[key])


async def _patient_context(session: AsyncSession, scope: TenantScope, patient_id: str):
    patient = await get_patient(session, scope, patient_id, required_scope="routine.read")
    tz = ZoneInfo(patient.timezone or "Asia/Bangkok")
    return patient, tz, now().astimezone(tz)


@care_action("orientation.answer")
async def answer_date(session: AsyncSession, scope: TenantScope, patient_id: str) -> dict:
    """"วันนี้วันอะไรนะ?" — ตอบเหมือนเดิมทุกครั้ง

    คำตอบขึ้นกับ "วันนี้" อย่างเดียว ไม่ขึ้นกับว่าถามมาแล้วกี่ครั้ง
    """
    patient, _, local = await _patient_context(session, scope, patient_id)
    answer = f"{thai_date(local.date())} เวลา {local.strftime('%H:%M')} น. ครับ 😊"

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=patient.patient_id,
        care_event_type="care.orientation.delivered",
        severity="low",
        transition={"from": None, "to": "delivered", "reason": "date question"},
        attributes={"record_type": "orientation", "patient_id": patient_id, "layer": "date"},
    )
    return {"layer": "date", "answer": answer, "date": local.date().isoformat()}


async def five_layers(session: AsyncSession, scope: TenantScope, patient_id: str) -> dict:
    """ทั้ง 5 ชั้น — ชั้นไหนไม่มีข้อมูลจะบอกว่าไม่มี ไม่เดาให้"""
    patient, tz, local = await _patient_context(session, scope, patient_id)
    today = local.date()

    place = patient.home_label or NO_DATA

    people: list[str] = []
    if feature_enabled(patient, "appointment"):
        for appointment in await appointments.upcoming(session, scope, patient_id, within_days=1):
            if appointment.starts_at.astimezone(tz).date() != today:
                continue
            who = appointment.doctor_name or "แพทย์"
            people.append(f"{who} เวลา {appointment.starts_at.astimezone(tz).strftime('%H:%M')} น.")

    plan = await routines.plan_for_date(session, scope, patient_id, today)

    return {
        "time": {"answer": f"{local.strftime('%H:%M')} น.", "value": local.isoformat()},
        "date": {"answer": thai_date(today), "value": today.isoformat()},
        "place": {"answer": place, "known": patient.home_label is not None},
        "person": {"answer": people or [NO_DATA], "known": bool(people)},
        "plan": {"items": plan, "known": bool(plan)},
    }


@care_action("orientation.brief.send")
async def daily_brief(session: AsyncSession, scope: TenantScope, patient_id: str) -> dict:
    """"วันนี้ของคุณ" — หน้าหลักที่ผู้ป่วยไม่ต้องคิดเองว่าต้องทำอะไร"""
    patient, tz, local = await _patient_context(session, scope, patient_id)
    today = local.date()
    layers = await five_layers(session, scope, patient_id)

    todays_appointments = []
    if feature_enabled(patient, "appointment"):
        for appointment in await appointments.upcoming(session, scope, patient_id, within_days=1):
            if appointment.starts_at.astimezone(tz).date() != today:
                continue
            todays_appointments.append(
                {
                    "time": appointment.starts_at.astimezone(tz).strftime("%H:%M"),
                    "doctor_name": appointment.doctor_name,
                    "purpose": appointment.purpose,
                    "appointment_id": appointment.appointment_id,
                }
            )

    medication_items: list[dict] = []
    if feature_enabled(patient, "medication"):
        for version in await medications.current_regimen(session, scope, patient_id):
            for entry in version.schedule or []:
                medication_items.append(
                    {
                        "time": entry.get("time", ""),
                        "name": version.name,
                        "dose": entry.get("dose", ""),
                        "relation_to_meal": entry.get("relation_to_meal"),
                        "needs_reconciliation": version.status == "needs_reconciliation",
                    }
                )
        medication_items.sort(key=lambda item: item["time"])

    brief = {
        "patient_id": patient_id,
        "display_name": patient.display_name,
        "date": layers["date"]["answer"],
        "time": layers["time"]["answer"],
        "place": layers["place"]["answer"],
        "appointments": todays_appointments,
        "medications": medication_items,
        "plan": layers["plan"]["items"],
        "text": _render(patient.display_name, layers, todays_appointments, medication_items),
    }

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=patient_id,
        care_event_type="care.orientation.delivered",
        severity="low",
        transition={"from": None, "to": "delivered", "reason": "daily brief"},
        attributes={
            "record_type": "orientation",
            "patient_id": patient_id,
            "layer": "daily_brief",
            "appointments": len(todays_appointments),
            "medications": len(medication_items),
        },
    )
    return brief


def _render(
    display_name: str, layers: dict, todays_appointments: list[dict], medications: list[dict]
) -> str:
    """ข้อความที่ผู้ป่วยได้ยิน/อ่าน — สั้น ชัด ไม่ตำหนิ ไม่ตีความอาการ"""
    lines = [
        f"สวัสดีครับ {display_name}",
        f"{layers['date']['answer']} เวลา {layers['time']['answer']}",
    ]
    if layers["place"]["known"]:
        lines.append(f"ตอนนี้อยู่ที่{layers['place']['answer']}ครับ")

    if todays_appointments:
        for appointment in todays_appointments:
            who = f"คุณหมอ{appointment['doctor_name']}" if appointment["doctor_name"] else "คุณหมอ"
            purpose = f" ({appointment['purpose']})" if appointment["purpose"] else ""
            lines.append(f"วันนี้มีนัด{who} เวลา {appointment['time']} น.{purpose}")
    else:
        lines.append("วันนี้ไม่มีนัดคุณหมอครับ")

    if medications:
        pending = [m for m in medications if m["needs_reconciliation"]]
        lines.append(f"วันนี้มียา {len(medications)} รายการตามตารางครับ")
        if pending:
            # 🔒 ยาที่ยังสะสางไม่เสร็จ ห้ามบอกจำนวนเม็ดเหมือนปกติ (ADR-0005 ข้อ 4)
            lines.append("มียาบางรายการที่รอให้ผู้ดูแลตรวจสอบก่อน ผมจะยังไม่บอกจำนวนนะครับ")

    # 🔒 "รายการถัดไป" ต้องเป็นสิ่งที่ผู้ป่วยลงมือทำเองเท่านั้น
    #    การเตือนล่วงหน้าเรื่องนัด (source_kind = appointment) ไม่ใช่งานที่ต้องทำวันนี้
    #    ถ้าเอามาปนจะกลายเป็น "รายการถัดไปคือ นัดพรุ่งนี้" ซึ่งชวนให้ผู้ป่วยเข้าใจผิดว่าต้องไปวันนี้
    remaining = [
        item
        for item in layers["plan"]["items"]
        if not item["confirmed"] and item["kind"] != "appointment"
    ]
    if remaining:
        nearest = remaining[0]
        lines.append(f"รายการถัดไปคือ {nearest['label']} เวลา {nearest['time']} น.")
    return "\n".join(lines)


@care_action("orientation.answer")
async def what_happens_on(
    session: AsyncSession, scope: TenantScope, patient_id: str, expression: str
) -> dict:
    """"พรุ่งนี้ต้องทำอะไรนะ?" — resolve คำบอกเวลาเป็นวันที่จริงแล้วค้นจาก timeline"""
    patient, tz, local = await _patient_context(session, scope, patient_id)
    day = resolve_day(expression, today=local.date())
    plan = await routines.plan_for_date(session, scope, patient_id, day)

    day_appointments = []
    if feature_enabled(patient, "appointment"):
        for appointment in await appointments.upcoming(session, scope, patient_id, within_days=30):
            if appointment.starts_at.astimezone(tz).date() == day:
                day_appointments.append(
                    {
                        "time": appointment.starts_at.astimezone(tz).strftime("%H:%M"),
                        "doctor_name": appointment.doctor_name,
                        "purpose": appointment.purpose,
                    }
                )

    await audit.emit(
        session,
        scope,
        event_type="STATE_TRANSITION",
        subject_type="record",
        subject_id=patient_id,
        care_event_type="care.orientation.delivered",
        severity="low",
        transition={"from": None, "to": "delivered", "reason": f"plan question: {expression}"},
        attributes={
            "record_type": "orientation",
            "patient_id": patient_id,
            "layer": "plan",
            "resolved_date": day.isoformat(),
        },
    )
    return {
        "expression": expression,
        "date": day.isoformat(),
        "date_answer": thai_date(day),
        "plan": plan,
        "appointments": day_appointments,
        # 🔒 ไม่มีข้อมูลคือไม่มีข้อมูล ไม่ใช่ "ไม่มีอะไรต้องทำ"
        "has_data": bool(plan or day_appointments),
        "answer": NO_DATA if not (plan or day_appointments) else None,
    }


async def who_is_around(session: AsyncSession, scope: TenantScope, patient_id: str) -> list[dict]:
    """ชั้น PERSON — ใครดูแลอยู่บ้าง (จากทีมดูแลจริง ไม่ใช่ความจำของ AI)"""
    team = await care_team(session, scope, patient_id)
    return [
        {"display_name": c.display_name, "relation": c.relation, "channel": c.channel}
        for c in team
    ]
