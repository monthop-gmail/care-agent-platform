"""ชุดปิดของ `attributes` — audit เก็บ **ตัวชี้** ไม่ใช่ **เนื้อหา**

`event/v1` นิยาม `metadata` ไว้แค่ `{"type": "object"}` คือเปิดทั้งหมด สิ่งเดียวที่ห้ามคือ
private reasoning / chain-of-thought · แปลว่าใครก็ตามที่เขียนโดเมนใส่อะไรลงไปก็ได้
และมันจะไปโผล่ใน audit trail ที่ผู้อ่านนอกระบบเห็นได้ตลอดไป

เราเคยใช้ช่องนั้นแบบเปิดจริง แล้วพบว่าตัวเองเก็บของพวกนี้ลง audit:

* ชื่อยาคู่กับ `patient_id` — ข้อมูลสุขภาพของบุคคลที่ระบุตัวได้ ไม่ใช่ metadata
* ข้อความเตือนที่ส่งให้ผู้ป่วยทั้งประโยค ซึ่ง interpolate ชื่อของสิ่งที่ต้องทำเข้าไป
* เหตุผลที่ **คนพิมพ์** ตอนกดอนุมัติ/ตอนหยุดคำสั่งของหมอ
* `**detail` ที่กาง dict ของโดเมนลง audit ทั้งก้อน

ทุกตัวมี row ของโดเมนอยู่แล้ว และ event มี `subject_id` ชี้ไปถึง row นั้นอยู่แล้ว
การก๊อปเนื้อหามาไว้ใน audit จึงไม่ได้เพิ่มความสามารถในการตรวจสอบ แต่เพิ่มที่เก็บ PII
ขึ้นมาอีกที่หนึ่ง — ที่ที่ **ลบไม่ได้** เพราะ audit เป็น append-only

กฎที่ไฟล์นี้บังคับ:

1. คีย์ที่ไม่ได้ประกาศไว้ที่นี่ → `emit()` reject · เพิ่มคีย์ใหม่ = ต้องมาเขียนบรรทัดที่นี่
   ซึ่งเป็นจุดที่คนเขียนต้องตอบว่าค่านี้เป็นตัวชี้หรือเป็นเนื้อหา
2. ค่าต้องตรงกับ *ชนิด* ที่ประกาศ · ชนิดทั้งหมดเป็นตัวชี้/รหัส/ตัวเลข/เวลา/boolean
   **ไม่มีชนิดสำหรับข้อความเสรี** ยกเว้น `system_text` ซึ่งมีคีย์เดียวและเป็นข้อความที่
   โค้ดของเราเองสร้างจาก policy ไม่ใช่ค่าที่ผู้ใช้พิมพ์หรือค่าจาก record ของผู้ป่วย

ข้อที่กฎนี้ **ไม่ได้** ปิด และต้องพูดให้ตรง: `transition.reason` กับ `error.message` เป็น
ฟิลด์ข้อความที่ `event/v1` นิยามเอง อยู่นอกกล่องนี้ · เหตุผลที่คนพิมพ์ตอนหยุดคำสั่งของหมอ
ยังอยู่ที่นั่น เพราะ ADR-0006 บังคับว่าต้องตอบได้ว่าหยุดเพราะอะไร และไม่มีที่อื่นเก็บ
ดู ADR-0011
"""

from __future__ import annotations

import re
from typing import Any

# ── ชนิดของค่าที่ audit เก็บได้ ────────────────────────────────────────────────
#
# ทุกชนิดตอบคำถามเดียวกันได้ว่า "ค่านี้เป็นของที่ระบบสร้างหรือของที่คนเขียน"
# ถ้าเป็นของที่คนเขียน มันประกาศไม่ได้ — ให้เก็บบน row ของโดเมนแล้วชี้ด้วย subject_id
# 🔒 `id` ที่นี่หลวมกว่า `identity/v1 $defs.Id` โดยตั้งใจ — ค่าบางตัวเป็น int PK ของตาราง
#    ภายใน และบางตัวเป็นตัวชี้ของระบบข้างนอก (device_id) ซึ่งไม่ได้อยู่ใต้ pattern ของ platform
#    สิ่งที่บังคับตรงกันคือ "ต้องเป็นตัวชี้ ไม่ใช่เนื้อหา"
ID = "id"                  # identifier ของ record ในระบบเรา (str หรือ int PK)
ID_LIST = "id_list"        # list ของ identifier
REF = "ref"                # ตัวชี้ข้ามชนิด เช่น "record:pat_x"
CODE = "code"              # ค่าจาก vocabulary ปิดของเรา — token ASCII คำเดียว
CODE_LIST = "code_list"
COUNT = "count"            # จำนวนเต็ม
NUMBER = "number"          # ตัวเลข (รวม float เช่น confidence)
TIME = "time"              # วันที่/เวลา/เวลาในตาราง — ISO หรือ HH:MM
FLAG = "flag"              # boolean
FLAG_MAP = "flag_map"      # dict[str, bool] เช่น care_profile
SYSTEM_TEXT = "system_text"  # ข้อความที่โค้ดของเราสร้างเอง · ดูข้อจำกัดด้านล่าง

MAX_CODE_LEN = 64
MAX_REF_LEN = 128
MAX_SYSTEM_TEXT_LEN = 240

# 🔒 token ต้องเป็น ASCII — ไม่ใช่แค่ "ไม่มีช่องว่าง"
#    ภาษาไทยเขียนติดกันโดยไม่มีช่องว่าง ประโยคเต็มประโยคจึงผ่านกฎ "ห้ามมีช่องว่าง" ได้สบาย
#    (เจอตอนเขียนเทสว่าคีย์ที่ประกาศแล้วยังรับข้อความของคนได้อยู่)
_TOKEN_RE = re.compile(rf"^[A-Za-z0-9][A-Za-z0-9._:@+/-]{{0,{MAX_CODE_LEN - 1}}}$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$|^\d{2}:\d{2}$")

# ── ทะเบียนคีย์ ───────────────────────────────────────────────────────────────
#
# คีย์ → (ชนิด, สิ่งที่มันชี้ไป) · คอลัมน์ที่สองไม่ใช่คำอธิบายให้อ่านเล่น
# มันคือคำตอบว่าถ้าอยากได้ "เนื้อหา" ต้องไปอ่านที่ไหน
DECLARED: dict[str, tuple[str, str]] = {
    # ── ตัวชี้ไปยัง row ของโดเมน ──
    "patient_id": (ID, "care_patient"),
    "subject_id": (ID, "บุคคลที่ consent พูดถึง (ap_consent_grant.subject_id)"),
    "grantee_id": (ID, "ผู้ได้รับสิทธิ์ใน consent"),
    "principal_id": (ID, "ผู้ใช้/ผู้ดูแลใน identity/v1"),
    "authority_id": (ID, "คนที่ตัดสินใบอนุมัติ (ap_approval.authority)"),
    "by": (ID, "คนที่ถอนใบอนุมัติ"),
    "target": (ID, "ผู้รับการแจ้งเตือนหนึ่งราย"),
    "targets": (ID_LIST, "ผู้รับการแจ้งเตือนทั้งชุด"),
    "activity_id": (ID, "care_activity"),
    "appointment_id": (ID, "care_appointment"),
    "medication_id": (ID, "care_medication_version.medication_id"),
    "version_ids": (ID_LIST, "care_medication_version ที่ขัดกัน — ชื่อยา/ตารางอยู่บนแถวเหล่านี้"),
    "superseded": (ID_LIST, "version ที่ถูกแทนที่"),
    "organization_id": (ID, "care_organization — ชื่อองค์กรอยู่บนแถวนั้น"),
    "source_organization_id": (ID, "องค์กรที่เป็นที่มาของคำสั่ง"),
    "source_id": (ID, "id ของสิ่งที่ทำให้เกิดงานนี้ (คู่กับ source_kind)"),
    "request_id": (ID, "ap_approval_request"),
    "supersedes": (ID, "ใบอนุมัติเดิมที่ถูกแทนที่"),
    "device_id": (ID, "อุปกรณ์ที่รายงานสัญญาณเข้ามา"),
    "notification_id": (ID, "care_notification — **ตัวข้อความที่ส่งอยู่บนแถวนั้น**"),
    "aggregated_into_notification": (ID, "care_notification ที่ถูกรวมเข้าไป"),
    "subject_ref": (REF, "'<subject_type>:<subject_id>' ของสิ่งที่ใบอนุมัติพูดถึง"),

    # ── รหัสจาก vocabulary ปิดของเรา ──
    "record_type": (CODE, "ชนิดของ record ที่ event นี้พูดถึง"),
    "capability": (CODE, "capability ใน policies/care-authority-map.yaml"),
    "authority_required": (CODE, "authority ที่ policy บอกว่าต้องมี"),
    "authority_type": (CODE, "ชนิดของผู้ตัดสิน (human/agent/service)"),
    "decision": (CODE, "approved / rejected"),
    "required_scope": (CODE, "scope ที่ถูกขอตอนตรวจ consent"),
    "scopes": (CODE_LIST, "scope ในใบยินยอม"),
    "conditions": (CODE_LIST, "kind ของเงื่อนไขในใบยินยอม — params อยู่บนแถวของใบ"),
    "purpose": (CODE, "วัตถุประสงค์ของใบยินยอม"),
    "activity_type": (CODE, "ชนิดของกิจวัตร"),
    "task_type": (CODE, "ชนิดของงานใน care plan"),
    "frequency": (CODE, "ชนิดของความถี่ (daily/weekly/...)"),
    "source_kind": (CODE, "ที่มาของงาน/สัญญาณ"),
    "settled_as": (CODE, "trail นี้จบแบบไหน"),
    "kind": (CODE, "ชนิดย่อยของ record นั้น ๆ"),
    "category": (CODE, "หมวดของของใช้ในบ้าน"),
    "layer": (CODE, "ชั้นของ orientation"),
    "entry_type": (CODE, "ชนิดของบันทึกใน journal"),
    "role": (CODE, "บทบาทของคนในบ้าน/องค์กร"),
    "audience": (CODE, "ผู้รับ (patient/caregiver)"),
    "channel": (CODE, "ช่องทางที่ส่งออก"),
    "instruction_source": (CODE, "คำสั่งนี้มาจากใคร (หมอ/ฉลาก/ผู้ดูแล)"),
    "requires": (CODE, "สิ่งที่ระบบบอกว่าต้องมีคนมาทำ"),
    "device_event": (CODE, "ชื่อเหตุการณ์จากอุปกรณ์ — ของนอกระบบ จึงบังคับให้เป็น token"),
    "awaits_external_event": (CODE, "ชื่อเหตุการณ์ที่ขั้นตอนนี้รออยู่"),

    # ── ตัวเลข ──
    "steps": (COUNT, "จำนวนขั้นตอน"),
    "attempts": (COUNT, "จำนวนครั้งที่เตือนไปแล้ว"),
    "attempt": (COUNT, "ครั้งที่เท่าไรของการเตือนนี้"),
    "event_count": (COUNT, "จำนวน event ใน trail ของงานนี้"),
    "cancelled_jobs": (COUNT, "จำนวนงานที่ถูกยกเลิกตามคำสั่งที่หยุด"),
    "counted_jobs": (COUNT, "จำนวนงานที่นับเข้าสรุปประจำวัน"),
    "stalled": (COUNT, "จำนวนงานที่ค้าง"),
    "stalled_minutes": (COUNT, "ค้างมากี่นาที"),
    "at_home_count": (COUNT, "จำนวนชิ้นที่ยังใช้ได้ในบ้าน"),
    "notified": (COUNT, "จำนวนคนที่ส่งถึงจริง"),
    "recipients": (COUNT, "จำนวนผู้รับสรุปประจำวัน"),
    "repeat_count": (COUNT, "สัญญาณเดิมซ้ำกี่ครั้งในหน้าต่างเดียวกัน"),
    "appointments": (COUNT, "จำนวนนัดของวันนั้น"),
    "medications": (COUNT, "จำนวนรายการยาของวันนั้น"),
    "version_count": (COUNT, "จำนวน version ที่ขัดกัน"),
    "confidence": (NUMBER, "ความมั่นใจของสัญญาณจากอุปกรณ์"),

    # ── เวลา ──
    "due_at": (TIME, "กำหนดของงาน"),
    "starts_at": (TIME, "เวลาเริ่มของนัด"),
    "expires_at": (TIME, "วันหมดอายุของใบยินยอม"),
    "expires_on": (TIME, "วันหมดอายุของของใช้"),
    "scheduled_time": (TIME, "เวลาในตารางประจำวัน (HH:MM)"),
    "local_date": (TIME, "วันตามเวลาท้องถิ่นของผู้ป่วย"),
    "resolved_date": (TIME, "วันที่ระบบตีความได้จากคำถาม"),

    # ── boolean ──
    "asked_directly": (FLAG, "รอบนี้ถามตรง ๆ หรือยัง"),
    "aggregated": (FLAG, "ถูกรวมกับสัญญาณเดิมแทนการสร้างใหม่"),
    "care_profile": (FLAG_MAP, "สวิตช์ของโหมดการดูแล"),
    "before": (FLAG_MAP, "care_profile ก่อนแก้"),
    "after": (FLAG_MAP, "care_profile หลังแก้"),

    # ── ข้อความเดียวที่ประกาศได้ ──
    #
    # 🔒 ประกาศได้เพราะ ap_policy เป็นคนสร้างประโยคนี้จาก authority_map + profile เท่านั้น
    #    ไม่มีค่าจาก record ของผู้ป่วยและไม่มีค่าที่ผู้ใช้พิมพ์ · ชื่อคีย์จงใจไม่ใช่ `reason`
    #    เพราะ `reason` เป็นชื่อที่ใครก็หยิบไปใส่ข้อความของคนได้โดยไม่รู้ตัว — และเราเคยทำ
    "policy_reason": (SYSTEM_TEXT, "ทำไม policy ตัดสินแบบนั้น (ap_policy สร้างเอง)"),
}


def problems(attrs: dict[str, Any]) -> list[str]:
    """คืนรายการปัญหา — ว่างแปลว่าผ่าน"""
    found: list[str] = []
    for key, value in attrs.items():
        declared = DECLARED.get(key)
        if declared is None:
            found.append(
                f"'{key}' ไม่ได้ประกาศไว้ — audit เก็บได้เฉพาะคีย์ใน "
                f"care_addons/ap_audit/attributes.py · ถ้าค่านี้เป็นเนื้อหา (ชื่อ ข้อความ "
                f"เหตุผลที่คนพิมพ์) ให้เก็บบน row ของโดเมนแล้วชี้ด้วย subject_id"
            )
            continue
        kind = declared[0]
        if value is None:
            continue          # "ไม่มีค่า" ไม่ใช่การละเมิดชนิด
        bad = _mismatch(kind, value)
        if bad:
            found.append(f"'{key}' ประกาศเป็น {kind} แต่ {bad}")
    return found


def _mismatch(kind: str, value: Any) -> str | None:
    if kind == ID:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return f"ไม่ใช่ identifier ({type(value).__name__})"
        return None if _TOKEN_RE.match(str(value)) else "ไม่ใช่ identifier (ต้องเป็น token ASCII)"
    if kind == REF:
        if not isinstance(value, str) or len(value) > MAX_REF_LEN or not value.strip():
            return "ไม่ใช่ตัวชี้"
        return None if _TOKEN_RE.match(value.replace(":", "")) else "ไม่ใช่ตัวชี้ (ต้องเป็น token ASCII)"
    if kind == CODE:
        if not isinstance(value, str):
            return f"ไม่ใช่รหัส ({type(value).__name__})"
        return None if _TOKEN_RE.match(value) else "ไม่ใช่รหัสจาก vocabulary ปิด (ต้องเป็น token ASCII)"
    if kind in (ID_LIST, CODE_LIST):
        if not isinstance(value, list):
            return f"ไม่ใช่ list ({type(value).__name__})"
        item_kind = ID if kind == ID_LIST else CODE
        for item in value:
            bad = _mismatch(item_kind, item)
            if bad:
                return f"สมาชิกในลิสต์{bad}"
        return None
    if kind == COUNT:
        return None if isinstance(value, int) and not isinstance(value, bool) else "ไม่ใช่จำนวนเต็ม"
    if kind == NUMBER:
        return None if isinstance(value, (int, float)) and not isinstance(value, bool) else "ไม่ใช่ตัวเลข"
    if kind == TIME:
        if not isinstance(value, str):
            return f"ไม่ใช่เวลา ({type(value).__name__})"
        return None if _TIME_RE.match(value) else "ไม่ใช่รูปเวลาที่อ่านได้ (ISO หรือ HH:MM)"
    if kind == FLAG:
        return None if isinstance(value, bool) else "ไม่ใช่ boolean"
    if kind == FLAG_MAP:
        if not isinstance(value, dict):
            return f"ไม่ใช่ dict ({type(value).__name__})"
        bad_keys = [k for k, v in value.items() if not isinstance(v, bool)]
        return f"มีค่าที่ไม่ใช่ boolean: {sorted(bad_keys)}" if bad_keys else None
    if kind == SYSTEM_TEXT:
        if not isinstance(value, str):
            return f"ไม่ใช่ข้อความ ({type(value).__name__})"
        return None if len(value) <= MAX_SYSTEM_TEXT_LEN else f"ยาวเกิน {MAX_SYSTEM_TEXT_LEN} ตัวอักษร"
    return f"ชนิด '{kind}' ไม่รู้จัก"
