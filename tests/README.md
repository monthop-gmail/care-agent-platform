# tests/

โปรเจกต์นี้เน้น **scenario test มากกว่า unit test** — เพราะสิ่งที่ต้องพิสูจน์คือ
"ระบบทำสิ่งที่ถูกต้องกับผู้ป่วยจริงหรือเปล่า" ไม่ใช่ "ฟังก์ชันคืนค่าถูกไหม"

```bash
pytest tests/ -q                      # ทั้งหมด (รันบน sqlite ไม่ต้องมี Postgres)
pytest tests/test_scenario_care_loop.py -q
python conformance/drift_check.py     # contract ยังตรงกับ agent-platform ที่ pin ไว้
```

## ไฟล์

| ไฟล์ | ครอบคลุม |
|---|---|
| `test_boot.py` | ทุกโมดูลโหลดได้และ route ถูก mount |
| `test_scenario_care_loop.py` | **S1** ยืนยันแล้วจบวง · **S2** เงียบ → retry → missed → caregiver · เพดานการเตือน · caregiver รับเรื่องแล้วหยุด |
| `test_scenario_medication.py` | **S4** ยาชนกันไม่เลือกข้าง · **S9** agent แก้ยาเองไม่ได้ · version chain แบบ append-only · สรุปยาก่อนพบหมอ |
| `test_governance.py` | **S7** ไม่มีหลักฐาน = ไม่มีข้อมูล · **S8** ข้าม tenant ไม่ได้ · consent · การปฏิเสธ event ที่ ground ไม่ได้ · quiet hours |
| `test_architecture_rules.py` | กฎ 4 ข้อของ `ap_*` (ADR-0003) · ทุก capability ต้องมี risk ใน policy · ห้าม `datetime.now()` ตรง |
| `test_api_end_to_end.py` | ทั้งเส้นผ่าน HTTP จริง — login → tenant → patient → routine → tick → ack → audit |

## เวลาในเทส

ห้ามใช้ `sleep` และห้ามพึ่งเวลาจริง — ใช้ `FakeClock`:

```python
with FakeClock("2026-08-19T01:00:00+00:00") as clock:
    ...
    clock.advance(minutes=11)     # เลื่อนไปดูว่า retry ทำงานไหม
```

โค้ดทุกที่ต้องเรียก `care_addons.ap_tenancy.clock.now()` ไม่ใช่ `datetime.now()`
(มีเทสบังคับข้อนี้ใน `test_architecture_rules.py`)

## กรองข้อมูลด้วย tenant เสมอ แม้แต่ในเทส

`select(CareNotification)` ลอย ๆ จะไปเห็นของเทสอื่นที่รันก่อนหน้า ใช้ helper แทน:

```python
from tests.conftest import notifications, audit_events
rows = await notifications(session, tenant, patient.patient_id, "caregiver")
```

## ข้อควรรู้: pstack module loader กับตารางในเทส

loader หาว่าโมดูลมีตารางอะไรจากการ diff `Base.metadata` **ตอน import โมดูล**
แต่ไฟล์เทสถูก import ก่อน `create_app()` เสมอ พอถึงตอนโหลดจริง โมดูลอยู่ใน `sys.modules` แล้ว
diff จึงได้ว่างและตารางไม่ถูกสร้าง — `conftest._ensure_all_tables()` จึงสร้างตารางที่ขาดให้

ปัญหานี้ไม่เกิดใน production (ไม่มีใคร import addon ก่อน kernel) และจะหายไปเองเมื่อทุก addon
มี Alembic migration ของตัวเอง — ดูงานที่ค้างใน [`../architecture/team-plan.md`](../architecture/team-plan.md)

## เขียน scenario ใหม่

1. เริ่มจากประโยคที่ผู้ป่วย/ผู้ดูแลพูดได้จริง (ดู `ref/chatgpt-care-agent-design.md`)
2. เขียนสิ่งที่ระบบ **ต้องไม่ทำ** ด้วยเสมอ ไม่ใช่แค่สิ่งที่ต้องทำ
3. ยืนยันผ่าน audit event ไม่ใช่แค่ state ปัจจุบัน — ระบบต้องตอบได้ว่า "ทำไมถึงทำแบบนั้น"
