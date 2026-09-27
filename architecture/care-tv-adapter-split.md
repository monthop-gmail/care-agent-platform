# `care-tv-adapter` — แผนแยก track และสัญญาที่ adapter จะ consume

**สถานะ:** แผน · ตอบ `task-07382a72` · ยังไม่มี repo และยังไม่มีโค้ด Android
**ขึ้นกับ:** `task-0efb0077` (foundation) ซึ่ง **merged แล้ว** ที่ `care-agent-platform#33`
— แผนนี้จึงอ้างสัญญาที่มีอยู่จริง ไม่ใช่ที่ยังไม่มี

ทุกตัวอย่างในเอกสารเป็นข้อมูลสมมติ

---

## 1. ขอบเขต repo

| | ถืออะไร | เหตุผล |
|---|---|---|
| `care-agent-platform` (นี่) | careplan · medication · reminder · policy · approval · audit · consent · **presentation intent** · **capability ของ device action** | คำถามของ **การดูแล** |
| `care-tv-adapter` (ใหม่) | render · TTS · ปุ่มรีโมท · การจับคู่อุปกรณ์ · lifecycle ของแอป · การลงมือกับอุปกรณ์จริง | คำถามของ **อุปกรณ์** |

เส้นแบ่งที่ใช้ตัดสิน: **ถ้าเปลี่ยนยี่ห้อ TV แล้วต้องแก้ มันอยู่ฝั่ง adapter**

### ห้ามย้ายเข้า adapter เด็ดขาด

careplan · medication · policy · approval · audit · consent · การตัดสินว่า `surface` ไหน
ได้จริง (`effective_presentation()`)

เหตุผลไม่ใช่ความสะอาด: `quiet hours` กับ `severity` เป็นกติกาของ **การดูแล** ถ้าย้ายไปฝั่ง
อุปกรณ์ ทุกยี่ห้อต้อง implement ใหม่และจะตีความไม่ตรงกัน — แล้วจะไม่มีใครตอบได้ว่า
ตกลงตอนตีสามผู้ป่วยเห็นอะไร

### ห้ามเข้าสัญญากลาง

`TrueID` · Android API · ชื่อ intent ของ vendor · ขนาดจอ · รหัสปุ่มรีโมท
`dwell` เป็น code (`short` / `medium` / `until_answered`) ไม่ใช่วินาที ก็เพราะข้อนี้

---

## 2. สัญญาที่ adapter จะ consume — ของจริงทั้งหมด ไม่มีของที่ยังไม่มี

### ขาออก: ข้อความ + presentation

```python
# care_escalation/services.py::register_sender
async def send_via_tv(session, notification) -> tuple[bool, str | None]:
    ...
register_sender("tv", send_via_tv)
```

`notification` ที่ได้รับถือ `text` · `channel` · `severity` · `presentation` · `target_principal_id`
`presentation` เป็น dict ของ code ที่ผ่าน `effective_presentation()` มาแล้ว — **adapter
ไม่ต้องคิดเรื่อง quiet hours เลย** ได้อะไรมาก็แสดงตามนั้น

🔒 sender **ต้องไม่ raise** (`care_line/outbound.py:20` เป็นตัวอย่าง) — ช่องทางล่มต้องไม่ทำให้
closed loop ของผู้ป่วยคนอื่นหยุดตาม

### ขาเข้า: สามทาง ไม่มีของใหม่

```python
jobs.mark_presented(session, scope, notification_id)          # วางบนจอแล้ว — ไม่ใช่ evidence
jobs.acknowledge(session, scope, care_job_id, evidence_kind="patient_confirmed", done=True)
activities.external_signal(...)   /   safety.report_signal(...)
```

### ขาออก: device action

```python
endpoint.pause_media(session, scope, patient_id, trigger="reminder_due")
endpoint.resume_media(session, scope, patient_id, trigger="caregiver_request")
endpoint.cancel_media(session, scope, patient_id, trigger="safety_signal")
```

โดเมน **ตัดสินและบันทึก** · adapter **ลงมือ** — `care_endpoint/services.py` ไม่มีโค้ดที่คุยกับ
อุปกรณ์เลยแม้แต่บรรทัดเดียว

---

## 3. ⚠️ ข้อที่แผนนี้เจอและยังไม่มีคำตอบ — ทิศทางของ transport

ข้อความออก (`sender`) ทำงานได้เพราะ **เราเป็นคนเรียกออก** — LINE อยู่บนคลาวด์ เรียกถึงได้

TV อยู่ในบ้านคน หลัง NAT · **เราเรียกเข้าไปไม่ได้** และ device action ต้องไปถึงอุปกรณ์

| ทางเลือก | ผล |
|---|---|
| **adapter poll** — แอปบน TV ถาม endpoint ของเราเป็นระยะ | ไม่ต้องเปิดพอร์ตในบ้าน · latency เท่ากับรอบ poll · ง่ายที่สุดและ**เป็นทางที่แนะนำ** |
| adapter เปิด stream ค้างไว้ (SSE/WebSocket) | latency ต่ำ เหมาะกับ `pause` ที่ความเร็วคือความปลอดภัย · ต้องมีชั้นจัดการ connection ที่ยังไม่มี |
| เราเรียกเข้า | ❌ ใช้ไม่ได้กับอุปกรณ์ในบ้าน |

🔒 ข้อนี้กระทบ ADR-0015 โดยตรง: `pause` เป็น audited exception เพราะ **ความเร็วคือคุณสมบัติ
ด้านความปลอดภัย** แต่ถ้า transport เป็น poll ทุก 30 วินาที ความเร็วนั้นหายไปครึ่งหนึ่ง
โดยที่ policy ยังบอกว่าเร็ว

**ข้อเสนอ:** poll สำหรับ MVP + บันทึกช่องว่างนี้ไว้ตรง ๆ ว่า SLA จริงของ `pause` ถูกกำหนด
โดย transport ไม่ใช่โดย policy · ห้ามเขียนในเอกสารว่า "หยุดได้ทันที" จนกว่าจะวัดได้

---

## 4. identity ของอุปกรณ์ · auth · การจับคู่

ใช้รูปที่ `care_line` พิสูจน์แล้ว ไม่คิดใหม่:

* **principal ของ adapter** เป็น `service` (`care_line/outbound.py:25` ใช้ `Principal(type="service", id="care-line")`)
  → `care-tv` เป็นตัวที่สอง
* **การจับคู่** ใช้รูป `care_line_pairing_code` — โค้ดอายุสั้น + ผูกกับ `patient_id` + `role`
  🔒 **ห้ามบันทึกตัวโค้ดลง audit** — คำกำกับนี้อยู่ใน `care_line/services.py:99` แล้วเพราะ
  ใครอ่าน log ได้จะผูกอุปกรณ์แทนได้ทันที
* **สิทธิ์** — `dec-52f5da07` (hybrid) ให้ intersect ด้วย policy cap ที่เพิ่มสิทธิ์ไม่ได้
  โดยโครงสร้าง · adapter ควรได้ cap แคบ ๆ ที่มีแค่ present/ack/device action
* **ADR-0008** — ช่องทางของผู้ป่วยตอบด้วย intent router ที่กำหนดล่วงหน้า · รีโมทมีปุ่มจำกัด
  จำนวนจึงเข้าเงื่อนไขนี้อยู่แล้ว **ห้ามมีช่องพิมพ์อิสระบนจอ**

---

## 5. หน้าที่ขั้นต่ำของ adapter

1. รับ notification → แสดงตาม `presentation` ที่ได้มา (ไม่ตีความเพิ่ม)
2. อ่านออกเสียงเมื่อ `speak: true`
3. map ปุ่มรีโมท → สามเจตนา: ทำแล้ว · ยังไม่ได้ทำ · ขอความช่วยเหลือ
   **ไม่มีปุ่มปิด/ไม่สนใจ** (ADR-0014 ข้อ 6)
4. เรียก `mark_presented` เมื่อวางบนจอ · เรียก `acknowledge` เมื่อคนกด
5. ลงมือกับอุปกรณ์เมื่อได้รับ device action
6. จับคู่อุปกรณ์ + จัดการ lifecycle ของแอป

**ไม่ใช่หน้าที่ adapter:** ตัดสินว่าควรเตือนไหม · ตัดสินว่าแสดงแบบไหน · เก็บสถานะของงาน

---

## 6. เกณฑ์รับงาน (acceptance criteria)

| # | เกณฑ์ |
|---|---|
| 1 | `register_sender("tv", …)` ทำงานโดย **ไม่แก้โค้ดใน `care_escalation` แม้บรรทัดเดียว** |
| 2 | ปุ่มบนรีโมทเรียกได้เฉพาะสามเจตนา และ `acknowledge(done=False)` ตั้ง backoff ต่อจริง |
| 3 | `mark_presented` **ไม่ปิดงาน** — เทสฝั่งเรามีแล้ว adapter ต้องไม่หาทางอ้อม |
| 4 | quiet hours ทำงานโดย adapter ไม่รู้เรื่องมันเลย (ทดสอบด้วยการส่งเวลาต่างกันสองรอบ) |
| 5 | `pause` วัด latency จริงจาก transport ได้ และตัวเลขนั้นถูกบันทึก ไม่ใช่อ้างว่า "ทันที" |
| 6 | ไม่มี `TrueID`/Android identifier ใดโผล่ใน `care-agent-platform` (grep ต้องว่าง) |
| 7 | ไม่มีการส่งข้อมูลพฤติกรรมการดูสื่อกลับมา (grep + code review) |

---

## 7. backlog ที่เริ่มได้ทันทีหลัง interface freeze

```text
A. scaffold repo + sender ที่ส่งเข้า stub แล้ว log (ไม่มี TV จริง)     ← เริ่มได้เลย
B. contract test ฝั่ง adapter ที่ยิงเข้า care API จริงด้วย synthetic patient
C. remote key mapping + สามเจตนา
D. transport poll + วัด latency ของ pause
E. pairing flow ตามรูป care_line
F. Android TV / TrueID integration                                  ← ท้ายสุดโดยเจตนา
```

ข้อ A–E **ไม่ต้องมี TV จริงเลย** และทำให้สัญญาถูกพิสูจน์ก่อนแตะ vendor ตัวไหน
ซึ่งเป็นเหตุผลเดียวกับที่ `payload_check` ของเรารัน scenario จริงแทนการเชื่อ fixture

## สิ่งที่แผนนี้ยังไม่ครอบ

media intervention ตามพฤติกรรมการดูสื่อ — ต้องเก็บข้อมูลชนิดใหม่ · ชนข้อจำกัดที่
`platform-contract.yaml` ประกาศไว้ และรอ `task-4c4a109f`
