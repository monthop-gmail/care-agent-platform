"""กำหนดตายของงานที่ส่งออกไปที่อุปกรณ์ — โดเมนตัดสิน อุปกรณ์บังคับตาม (ADR-0016)

`adapters/care_tv/runtime.py` ทิ้ง envelope ที่เลย `expires_at` ได้แล้ว และเขียนกำกับไว้ว่า
**adapter ห้ามคิด TTL ขึ้นมาเอง** ไฟล์นี้คือฝั่งที่มีสิทธิ์คิด

🔒 ค่าทุกค่าในไฟล์นี้ต้องอธิบายได้ด้วย **ความหมายของงาน** ไม่ใช่ด้วยตัวเลขที่เลือกมาเฉย ๆ
   และตัวเลขที่เลี่ยงไม่ได้ต้องประกาศเพดานไว้ว่า tenant ยกขึ้นไม่ได้

🔒 ไฟล์นี้ไม่แตะกติกาของยา — `grace_minutes` ที่ใช้เป็นฐานคือค่าที่ทีมดูแลตั้งไว้ต่อกิจวัตร
   อยู่แล้ว และการตัดสินว่างาน `missed` ยังเป็น `attempts >= max_attempts` เหมือนเดิม
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.clock import now
from core.tenancy import TenantScope, scoped
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from care_addons.care_routine.models import CareRoutineItem

# ── ชนิดของกฎ ────────────────────────────────────────────────────────────────
WORK_WINDOW = "work_window"              # หมดอายุเมื่อช่วงเวลาของงานนั้นปิด
END_OF_LOCAL_DAY = "end_of_local_day"    # หมดอายุเมื่อวันของผู้ป่วยจบ
SHORT_FRESHNESS = "short_freshness"      # สดได้ไม่นาน · ต้องประกาศเพดาน
NEVER = "never"                          # ไม่หมดอายุ · **ต้องประกาศเหตุผล**


@dataclass(frozen=True)
class Rule:
    """หนึ่งกฎ พร้อมเหตุผลเชิงการดูแล — ไม่ใช่แค่ตัวเลข

    `ceiling_minutes` คือเพดานที่ tenant **ยกขึ้นไม่ได้** · ลดลงได้
    """

    rule: str
    reason: str
    minutes: int | None = None
    ceiling_minutes: int | None = None
    bounded_by_next_occurrence: bool = False
    default_grace_minutes: int | None = None


# ── ทะเบียนปิด: ชนิดของงาน → กฎ ──────────────────────────────────────────────
#
# 🔒 ชุดปิด · ชนิดที่ไม่อยู่ในนี้ต้องพัง ไม่ใช่ได้ค่าปริยายเงียบ ๆ
CLASSES: dict[str, Rule] = {
    "orientation": Rule(
        END_OF_LOCAL_DAY,
        "สรุปของวันนี้ที่ถูกอ่านเช้าวันรุ่งขึ้นไม่ใช่ข้อมูลเก่า มันคือ**ข้อมูลผิด** — "
        "ผู้ป่วยสมองเสื่อมใช้ข้อความนี้เพื่อรู้ว่าวันนี้วันอะไร",
    ),
    "medication_prompt": Rule(
        WORK_WINDOW,
        "เตือนกินยาที่ขึ้นจอหลังช่วงของมันปิด เชิญให้กินผิดเวลา และถ้าคาบเกี่ยวรอบถัดไป "
        "คือเชิญให้**กินซ้ำ** · จึงถูกตัดไม่ให้ข้ามรอบยาถัดไปเด็ดขาด",
        bounded_by_next_occurrence=True,
        default_grace_minutes=30,
    ),
    "routine_prompt": Rule(
        WORK_WINDOW,
        "เตือนกิจวัตรหลังช่วงเวลาของมันจบ คือชวนให้ทำผิดเวลา และทำให้ตารางของวันนั้นเลื่อนตามกันทั้งวัน",
        default_grace_minutes=30,
    ),
    "caregiver_help": Rule(
        NEVER,
        "ประกาศไว้ตรง ๆ ว่าไม่หมดอายุ — ความล้มเหลวของการหมดอายุในเส้นนี้คือ**ความเงียบ** "
        "และ 'ไม่มีใครถูกบอก' เป็นความเสียหายที่มองจากข้างนอกไม่เห็น · "
        "เส้นนี้จบด้วยคนรับเรื่อง หรือด้วยการถูกแทนด้วยใบใหม่ ไม่ใช่ด้วยนาฬิกา",
    ),
    "device_pause": Rule(
        WORK_WINDOW,
        "หยุดจอเพราะมีงานถึงกำหนด · ถ้างานนั้นหมดช่วงไปแล้ว การหยุดจอคือการรบกวน"
        "ที่ไม่มีคำอธิบายให้ผู้ป่วย และไม่มีใครตอบได้ว่าทำไมจอดับ",
        default_grace_minutes=30,
    ),
    "device_cancel": Rule(
        WORK_WINDOW,
        "อยู่ชั้นเดียวกับ `device_pause` ตามหลัก `tools.cancel` — ยกเลิกสิ่งที่เล่นอยู่"
        "เพราะเหตุเดียวกัน จึงหมดอายุพร้อมเหตุเดียวกัน",
        default_grace_minutes=30,
    ),
    "device_resume": Rule(
        SHORT_FRESHNESS,
        "🔒 เข้มกว่า `pause` โดยเจตนา (ADR-0015 ข้อ 4) — ระหว่างที่จอหยุด ผู้ป่วยอาจหลับไปแล้ว "
        "การเปิดต่อคือ**การปลุกคน** ไม่ใช่การยกเลิกการหยุด · คำสั่งเปิดต่อจึงสดได้เท่าที่"
        "คนยังนั่งอยู่หน้าจอในครั้งเดียวกันเท่านั้น หลังจากนั้นค่าปลอดภัยคือปล่อยให้จอดับ",
        minutes=1,
        ceiling_minutes=1,
    ),
    "caregiver_request_action": Rule(
        SHORT_FRESHNESS,
        "คนขอเมื่อครู่นี้และยืนอยู่ตรงนั้น · คำสั่งที่ไปถึงช้ากว่านั้นไม่ตรงกับสิ่งที่เขาเห็นแล้ว",
        minutes=2,
        ceiling_minutes=5,
    ),
    "safety_action": Rule(
        SHORT_FRESHNESS,
        "สัญญาณความปลอดภัยสดสั้น · เหตุการณ์อาจจบไปแล้ว แต่ให้ยาวกว่าคำขอของคน"
        "เพราะเน็ตหลุดตอนนั้นเป็นเรื่องที่เกิดได้",
        minutes=5,
        ceiling_minutes=10,
    ),
}

# trigger ของ device action → ชนิดของกฎ (`TRIGGERS` ใน services.py เป็นชุดปิดอยู่แล้ว)
ACTION_CLASS_BY_TRIGGER = {
    "reminder_due": {"pause": "device_pause", "cancel": "device_cancel", "resume": "device_resume"},
    "caregiver_request": {
        "pause": "caregiver_request_action",
        "cancel": "caregiver_request_action",
        "resume": "device_resume",
    },
    "safety_signal": {
        "pause": "safety_action",
        "cancel": "safety_action",
        "resume": "device_resume",
    },
}


class UnknownExpiryClass(ValueError):
    """ชนิดที่ไม่อยู่ในทะเบียน — ต้องพัง ไม่ใช่ได้ `None` เงียบ ๆ"""


def rule_for(expiry_class: str) -> Rule:
    if expiry_class not in CLASSES:
        raise UnknownExpiryClass(
            f"expiry class '{expiry_class}' ไม่อยู่ในทะเบียน {sorted(CLASSES)} — "
            f"ของที่ไม่มีกฎต้องไม่ถูกส่งออกไปโดยไม่มีกำหนดตายโดยไม่มีใครรู้"
        )
    return CLASSES[expiry_class]


def _end_of_local_day(tz_name: str, at: datetime) -> datetime:
    tz = ZoneInfo(tz_name)
    local = at.astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return midnight.astimezone(at.tzinfo)


def deadline_for(
    expiry_class: str,
    *,
    at: datetime | None = None,
    due_at: datetime | None = None,
    grace_minutes: int | None = None,
    next_due_at: datetime | None = None,
    timezone: str = "Asia/Bangkok",
) -> datetime | None:
    """ฟังก์ชันบริสุทธิ์ — คืน `None` **เฉพาะ** กฎที่ประกาศว่า `NEVER`

    🔒 `None` ในระบบนี้ต้องมาจากกฎที่เขียนเหตุผลไว้เท่านั้น ไม่ใช่จากการหาค่าไม่เจอ
    """
    rule = rule_for(expiry_class)
    at = at or now()

    if rule.rule == NEVER:
        return None
    if rule.rule == END_OF_LOCAL_DAY:
        return _end_of_local_day(timezone, at)
    if rule.rule == SHORT_FRESHNESS:
        minutes = min(rule.minutes or 0, rule.ceiling_minutes or rule.minutes or 0)
        return at + timedelta(minutes=minutes)

    # WORK_WINDOW — ฐานคือ `grace_minutes` ที่ทีมดูแลตั้งไว้ต่อกิจวัตรอยู่แล้ว
    base = due_at or at
    grace = grace_minutes if grace_minutes is not None else rule.default_grace_minutes or 0
    closes = base + timedelta(minutes=grace)
    if rule.bounded_by_next_occurrence and next_due_at is not None:
        # 🔒 ห้ามคาบเกี่ยวรอบถัดไปเด็ดขาด — นี่คือเพดาน ไม่ใช่ค่าที่ปรับได้
        closes = min(closes, next_due_at)
    return closes


# ── ผูกกับของจริงในฐานข้อมูล ─────────────────────────────────────────────────
SOURCE_CLASS = {"medication": "medication_prompt"}


def class_for_notification(notification, job=None) -> str:
    """ชนิดของกำหนดตายมาจากความหมายของงาน ไม่ใช่จากช่องทางที่ส่ง"""
    if notification.audience == "caregiver":
        return "caregiver_help"
    if job is None:
        return "orientation"
    return SOURCE_CLASS.get(job.source_kind, "routine_prompt")


async def _grace_and_next(
    session: AsyncSession, scope: TenantScope, job, rule: Rule
) -> tuple[int | None, datetime | None]:
    """อ่าน `grace_minutes` ของกิจวัตรต้นทาง และรอบถัดไปของงานเดียวกัน

    🔒 `grace_minutes` มีอยู่ในฐานข้อมูลตั้งแต่ schema แรกและ **ยังไม่มีใครอ่านมันเลย** ·
       ใบนี้ทำให้มันมีความหมาย โดยไม่เปลี่ยนการตัดสินว่างาน `missed` (ยังเป็น attempts)
    """
    item = await session.scalar(
        scoped(
            select(CareRoutineItem).where(CareRoutineItem.routine_id == job.source_id),
            CareRoutineItem,
            scope,
        )
    )
    grace = item.grace_minutes if item is not None else None

    next_due_at = None
    if rule.bounded_by_next_occurrence:
        from care_addons.care_escalation.models import CareJob

        next_due_at = await session.scalar(
            scoped(
                select(CareJob.due_at)
                .where(
                    CareJob.patient_id == job.patient_id,
                    CareJob.source_id == job.source_id,
                    CareJob.due_at > job.due_at,
                )
                .order_by(CareJob.due_at)
                .limit(1),
                CareJob,
                scope,
            )
        )
    return grace, next_due_at


async def for_notification(
    session: AsyncSession, scope: TenantScope, notification, *, job=None, patient=None
) -> tuple[datetime | None, str]:
    """ตัวเดียวที่ฝั่งส่งเรียก — คืน (กำหนดตาย, ชนิด) ให้เก็บลงแถวก่อนส่งออก"""
    expiry_class = class_for_notification(notification, job)
    rule = rule_for(expiry_class)
    if rule.rule == NEVER:
        return None, expiry_class

    grace = next_due_at = None
    if job is not None and rule.rule == WORK_WINDOW:
        grace, next_due_at = await _grace_and_next(session, scope, job, rule)

    deadline = deadline_for(
        expiry_class,
        at=notification.sent_at or now(),
        due_at=getattr(job, "due_at", None),
        grace_minutes=grace,
        next_due_at=next_due_at,
        timezone=getattr(patient, "timezone", None) or "Asia/Bangkok",
    )
    return deadline, expiry_class


def for_device_action(action: str, trigger: str, *, at: datetime | None = None) -> tuple[datetime, str]:
    """คำสั่งต่ออุปกรณ์ — ชนิดมาจาก **ที่มาของคำสั่ง** ไม่ใช่จากตัวคำสั่งอย่างเดียว"""
    by_action = ACTION_CLASS_BY_TRIGGER.get(trigger)
    if by_action is None or action not in by_action:
        raise UnknownExpiryClass(
            f"ไม่มีกฎกำหนดตายสำหรับ action '{action}' ที่มาจาก trigger '{trigger}'"
        )
    expiry_class = by_action[action]
    deadline = deadline_for(expiry_class, at=at)
    assert deadline is not None            # ไม่มี device action ไหนที่กฎเป็น NEVER
    return deadline, expiry_class


__all__ = [
    "CLASSES",
    "UnknownExpiryClass",
    "class_for_notification",
    "deadline_for",
    "for_device_action",
    "for_notification",
    "rule_for",
]
