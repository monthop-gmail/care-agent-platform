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

---

# ผลวัดจริง (2026-09-27 · `task-becbc14f`)

scaffold อยู่ที่ `adapters/care_tv/` · เทส contract 16 ตัวที่ `tests/test_care_tv_adapter.py`
รันใน CI ได้โดยไม่มี TV จริง

## ⚠️ เปลี่ยนจากแผน — scaffold ยังอยู่ใน repo นี้ ไม่ใช่ repo แยก

แผนข้างบนเสนอ repo แยก · สิ่งที่ทำจริงคือโฟลเดอร์ในนี้ และนี่คือเหตุผล:

* เกณฑ์รับงานข้อแรกคือ **เทสต้องรันใน CI โดยไม่มี TV จริง** ซึ่งต้องยิงเข้า care API จริง
* **repo แยกไม่ได้บังคับขอบเขตจริง** — repo แยกยัง `import` ของกันได้ถ้ามีคนติดตั้ง ·
  ที่บังคับจริงคือ `test_the_adapter_never_imports_domain_logic()` ซึ่งไล่ import
  ของทุกไฟล์ในแพ็กเกจแล้วฟ้องถ้าแตะ careplan · medication · ap_policy · ap_approval ·
  ap_audit · ap_consent
* การย้ายออกควรเกิดตอน **มีโค้ด vendor** เพราะตอนนั้นขอบเขตกลายเป็นเรื่อง build tooling
  กับจังหวะปล่อยของ ไม่ใช่เรื่องวินัยของคนเขียน

ย้ายโฟลเดอร์ออกได้ทั้งก้อนโดยไม่ต้องแก้ข้างใน

## latency ของ transport — วัดแล้ว ไม่ได้เดา

`python adapters/care_tv/benchmark.py --full` · seed คงที่ · เครื่อง dev ตัวเดียว

| รอบ poll | ตัวอย่าง | p50 | p95 | max |
|---|---|---|---|---|
| 0.1s | 40 | 0.053s | 0.097s | 0.097s |
| 0.25s | 40 | 0.122s | 0.245s | 0.249s |
| 0.5s | 40 | 0.246s | 0.478s | 0.485s |
| **1s** | 40 | **0.469s** | **0.915s** | **0.982s** |
| **5s** | 6 | **2.229s** | **4.501s** | **4.501s** |
| **15s** | 6 | **8.466s** | **14.217s** | **14.217s** |
| **30s** | 6 | **10.098s** | **25.489s** | **25.489s** |

รูปที่ได้ตรงกับที่คาด — เวลาที่งานถึงกำหนดไม่ซิงก์กับรอบ poll จึงได้ latency ~ U(0, interval)
ทำให้ **p50 ≈ ครึ่งรอบ · max → เต็มรอบ**

### สิ่งที่ตัวเลขนี้บอก และเป็นเหตุผลที่ต้องวัด

> **SLA จริงของ `pause` เป็นฟังก์ชันของรอบ poll ไม่ใช่ของ policy**
>
> ADR-0015 ให้ `pause` เป็น audited exception เพราะความเร็วคือคุณสมบัติด้านความปลอดภัย
> แต่ที่รอบ poll 30 วินาที **ครึ่งหนึ่งของคำสั่งหยุดใช้เวลาเกิน 10 วินาที และหางยาวถึง 25 วินาที**
> — ไม่มีอะไรใน policy ที่บอกเรื่องนี้ได้

**ห้ามเขียนในเอกสารใดว่า "หยุดได้ทันที"** · ถ้าต้องการ p95 ต่ำกว่า 1 วินาที ต้องใช้รอบ poll
1 วินาที ซึ่งแลกมาด้วย request ประมาณ 86,400 ครั้งต่อเครื่องต่อวัน หรือต้องมี stream
ซึ่ง **ยังไม่มีชั้นจัดการ connection** และ `StreamTransport` จึง `raise NotImplementedError`
โดยเจตนา ไม่ได้ทำเหมือนมี

### ข้อแลกเปลี่ยนที่ต้องเลือกด้วยข้อมูลนี้

| รอบ poll | p95 | request/เครื่อง/วัน | เหมาะกับ |
|---|---|---|---|
| 1s | ~0.9s | ~86,400 | เครื่องเสียบไฟ · เน็ตบ้าน · ต้องการหยุดเร็ว |
| 5s | ~4.5s | ~17,280 | สมดุลที่เสนอสำหรับ MVP |
| 30s | ~25s | ~2,880 | ประหยัดสุด · **ไม่เหมาะกับ `pause` เชิงความปลอดภัย** |

## สิ่งที่พิสูจน์แล้วด้วยเทส

| เกณฑ์ | เทส |
|---|---|
| ลงทะเบียนได้โดยไม่แก้ `care_escalation` | `test_the_adapter_registers_without_touching_care_escalation` |
| adapter ไม่ประเมิน quiet hours ซ้ำ | `test_the_adapter_receives_the_domain_decision_and_does_not_redo_it` · `test_render_is_a_pure_function_of_the_intent_it_was_given` |
| `mark_presented` ไม่ปิดงานและไม่สร้าง evidence | `test_presented_through_the_adapter_still_does_not_close_work` |
| ปุ่ม map แบบ deterministic · ไม่มีปุ่มปิด | `test_remote_keys_map_deterministically_to_the_three_intents` · `test_an_unmapped_remote_key_is_refused_instead_of_guessed` |
| `pause` ไม่รอใครก่อนเข้าคิว | `test_publishing_a_pause_never_waits_for_anyone` |
| latency ถูกคุมด้วยรอบ poll | `test_latency_is_bounded_by_the_poll_interval_not_by_policy` |
| ไม่มีชื่อ vendor ในสัญญากลาง | `test_no_vendor_identifier_leaks_into_the_contract` |
| ไม่มีการเก็บพฤติกรรมการดูสื่อ | `test_nothing_collects_media_viewing_behaviour` |
| credential ไม่มี PII · โค้ดจับคู่ไม่หลุดเข้า log | `test_credentials_carry_no_patient_data_and_never_print_the_token` · `test_a_pairing_code_can_be_redacted_before_it_reaches_a_log` |

## สิ่งที่แผนนี้ยังไม่ครอบ

media intervention ตามพฤติกรรมการดูสื่อ — ต้องเก็บข้อมูลชนิดใหม่ · ชนข้อจำกัดที่
`platform-contract.yaml` ประกาศไว้ และรอ `task-4c4a109f`
