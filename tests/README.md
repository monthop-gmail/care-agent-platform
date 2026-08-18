# tests/

โปรเจกต์นี้เน้น **scenario test มากกว่า unit test** — เพราะสิ่งที่ต้องพิสูจน์คือ
"ระบบทำสิ่งที่ถูกต้องกับผู้ป่วยจริงหรือเปล่า" ไม่ใช่ "ฟังก์ชันคืนค่าถูกไหม"

```bash
pytest tests/ -q                          # ทั้งหมด (sqlite — ไม่ต้องมี Postgres)
pytest tests/test_scenario_care_loop.py -q
python conformance/drift_check.py         # contract ยังตรงกับ agent-platform ที่ pin ไว้
python conformance/migration_check.py     # migration ยังตรงกับ models

# แบบเดียวกับ CI และ production
PSTACK_DATABASE_URL="postgresql+asyncpg://care:care@localhost:55432/care_test" pytest tests/ -q
```

CI รันชุดนี้ **สองรอบ** (matrix `sqlite` + `postgres`) — เทสที่ผ่านบน sqlite อย่างเดียว
ไม่พอ เพราะข้อจำกัดจริงหลายอย่างโผล่เฉพาะบน Postgres

## ไฟล์

| ไฟล์ | ครอบคลุม |
|---|---|
| `test_boot.py` | ทุกโมดูลโหลดได้และ route ถูก mount |
| `test_scenario_care_loop.py` | **S1** ยืนยันแล้วจบวง · **S2** เงียบ → retry → missed → caregiver · เพดานการเตือน · caregiver รับเรื่องแล้วหยุด |
| `test_scenario_medication.py` | **S4** ยาชนกันไม่เลือกข้าง · **S9** agent แก้ยาเองไม่ได้ · version chain แบบ append-only · สรุปยาก่อนพบหมอ |
| `test_scenario_appointment.py` | **S5** เตรียมตัวไปพบหมอทีละขั้น · ขั้นที่ค้าง → caregiver · fasting ต้องมีเอกสาร · "รับทราบว่ามีนัด" ≠ "ไปมาแล้ว" · visit brief |
| `test_scenario_orientation.py` | **S3** ถามวันที่ซ้ำ 3 ครั้งได้คำตอบเดิม (และไม่มีถ้อยคำตำหนิ) · ชั้นที่ไม่มีข้อมูลบอกว่าไม่มี · daily brief · temporal memory ("พรุ่งนี้") |
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

## engine ของเทสแยกจาก engine ของ kernel

fixture `session` สร้าง engine ของตัวเองแทนการใช้ engine global — เพราะ `TestClient`
รัน lifespan ในลูปของมันเอง และ engine ที่ถูกสร้างตรงนั้นผูกกับลูปนั้นถาวร
พอเทส async ตัวถัดไป (คนละ event loop) หยิบไปใช้ asyncpg จะโยน
`attached to a different loop` ทันที (aiosqlite ไม่โยนเพราะทำงานบน thread —
บั๊กนี้จึงโผล่ตอนเปิด Postgres ใน CI เท่านั้น)

## เขียน scenario ใหม่

1. เริ่มจากประโยคที่ผู้ป่วย/ผู้ดูแลพูดได้จริง (ดู `ref/chatgpt-care-agent-design.md`)
2. เขียนสิ่งที่ระบบ **ต้องไม่ทำ** ด้วยเสมอ ไม่ใช่แค่สิ่งที่ต้องทำ
3. ยืนยันผ่าน audit event ไม่ใช่แค่ state ปัจจุบัน — ระบบต้องตอบได้ว่า "ทำไมถึงทำแบบนั้น"
