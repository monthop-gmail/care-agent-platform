"""ปุ่มรีโมท → เจตนา — ชุดปิดสามค่า (ADR-0008 · ADR-0014 ข้อ 6)

🔒 ไม่มีเจตนา "ปิด/ไม่สนใจ" เพราะการปิดข้อความเตือนยาโดยไม่มีสถานะ คือการทำให้งาน
   หายไปเงียบ ๆ ซึ่งขัด `no silent state change` ที่ repo นี้ pin ไว้เป็น frozen guarantee

🔒 ไม่มีช่องพิมพ์อิสระบนจอ — รีโมทมีปุ่มจำกัดจำนวน ซึ่งทำให้เข้าเงื่อนไขของ ADR-0008
   ได้ง่ายกว่า LINE
"""

from __future__ import annotations

DONE = "done"
NOT_YET = "not_yet"
HELP = "help"

INTENTS = [DONE, NOT_YET, HELP]

# รหัสปุ่มของ Android เป็นของ adapter ไม่ใช่ของสัญญา — map ไว้ที่เดียว
KEY_MAP = {
    "DPAD_CENTER": DONE,
    "BUTTON_A": DONE,
    "BACK": NOT_YET,
    "BUTTON_B": NOT_YET,
    "BUTTON_Y": HELP,
}


class UnmappedKey(KeyError):
    """ปุ่มที่ไม่ได้ map ต้องไม่ถูกเดาเป็นเจตนาใด — เงียบดีกว่าเดาผิด"""


def intent_for(key: str) -> str:
    if key not in KEY_MAP:
        raise UnmappedKey(
            f"ปุ่ม '{key}' ไม่ได้ map เป็นเจตนา — เจตนาที่มีคือ {INTENTS} "
            f"(เพิ่มปุ่มได้ที่ KEY_MAP แต่เพิ่มเจตนาต้องแก้ ADR-0014 ก่อน)"
        )
    return KEY_MAP[key]
