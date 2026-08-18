# ADR-0005: medication เป็น append-only version chain ห้าม overwrite

**Status:** Accepted (2026-08-18)
**Depends on:** [ADR-0004](0004-care-event-vocabulary.md)

## Context

ผู้ป่วยหนึ่งคนมีหมอหลายคน และทุกครั้งที่ไปพบหมอ ยาจะถูก เพิ่ม / ลด / หยุด / เปลี่ยนขนาด
ปัญหาจริงที่ผู้ใช้เล่า (`ref` §"รายละเอียดของยาแต่ละมื้อ") ไม่ใช่ "ลืมกินยา" แต่คือ
**จำไม่ได้ว่าใครสั่งอะไร เปลี่ยนเมื่อไร มื้อไหน ก่อนหรือหลังอาหาร และคำสั่งเก่าถูกยกเลิกไปหรือยัง**

ถ้าเก็บแค่สถานะปัจจุบัน (`ยา X = หยุด`) ระบบจะตอบคำถาม "เมื่อก่อนกินยังไง" ไม่ได้
และที่แย่กว่าคือ ถ้ามีการบันทึกผิด จะไม่มีทางรู้ว่าผิดตอนไหนและใครเป็นคนแก้

## Decision

### 1. medication เป็น chain ของ version ที่ append อย่างเดียว

```
Medication X   (medication_id คงที่ตลอดอายุของยาตัวนี้)
├── v1  01 Aug  Doctor A   1 tablet morning     SUPERSEDED
├── v2  10 Aug  Doctor B   0.5 tablet morning   SUPERSEDED
└── v3  18 Aug  Doctor A   STOP                 ACTIVE
```

- แถวเก่า **ห้าม UPDATE ห้าม DELETE** — เปลี่ยนได้แค่ field `status` จาก `active` → `superseded`
  พร้อม `superseded_by` ที่ชี้ไปเวอร์ชันใหม่ (นี่คือการ "ปิดสมุด" ไม่ใช่การแก้ของเก่า)
- ทุกเวอร์ชันต้องมี `prescribed_by` (หมอคนไหน) · `instruction_source` · `effective_from`
- คำถาม "ตอนนี้ต้องกินยังไง" ตอบจาก **version ที่ active เท่านั้น**
  คำถาม "เมื่อก่อนกินยังไง" ตอบจาก chain
- ทุกการสร้างเวอร์ชันใหม่ออก event `care.medication.changed`

### 2. `relation_to_meal` เป็น structured data ไม่ใช่ข้อความ

```
before_meal · with_meal · after_meal · empty_stomach · bedtime · morning · as_needed · specific_time
```

ค่าที่ไม่รู้จักให้ปฏิเสธที่ intake — ห้ามให้ LLM แปลงข้อความอิสระเป็นค่าเหล่านี้แล้วเขียนลง DB เอง
(ต้องผ่านการยืนยันของคน ดู [ADR-0006](0006-ai-has-no-medical-authority.md))

### 3. `instruction_source` บังคับ — ต้องรู้เสมอว่าข้อมูลมาจากไหน

```
doctor_instruction · pharmacy_label · hospital_document · caregiver_entry · patient_entry
```

ข้อมูลจาก `patient_entry` มีน้ำหนักไม่เท่ากับ `doctor_instruction` และ UI ต้องแสดงต่างกัน
— ผู้ป่วยที่มีภาวะความจำเสื่อมอาจบันทึกผิด และระบบต้องไม่ทำให้ของที่ผู้ป่วยจำมาเอง
กลายเป็นคำสั่งแพทย์โดยไม่ตั้งใจ

### 4. ยาชนกันไม่ใช่หน้าที่ agent ตัดสิน

ถ้ามีมากกว่าหนึ่ง active version ของสารตัวเดียวกันจากหมอคนละคน:

```
Doctor A: 1 tablet   ─┐
                      ├─→ care.medication.conflict → NEEDS_RECONCILIATION → caregiver/doctor
Doctor B: 0.5 tablet ─┘
```

ระบบ **detect และหยุด** — ไม่เลือกข้าง ไม่รวมขนาด ไม่เดาว่าใบสั่งล่าสุดถูกเสมอ
สถานะ `needs_reconciliation` ทำให้ reminder ของยาตัวนั้นแสดงคำเตือนแทนที่จะบอกจำนวนเม็ด

## Consequences

- ตาราง `care_medication_version` โตเรื่อย ๆ ตามจำนวนครั้งที่พบหมอ — รับได้ (ผู้ป่วยหนึ่งคนไม่กี่ร้อยแถวต่อปี)
- query "ยาวันนี้" ต้อง join active version เสมอ — ทำ index `(patient_id, status)` ตั้งแต่ migration แรก
- สรุปยาก่อนพบหมอ (medication reconciliation) สร้างจาก chain ได้ฟรี ไม่ต้องเก็บแยก
- การ import จากโรงพยาบาล/ร้านยาในอนาคตเป็นแค่ `instruction_source` ตัวใหม่ ไม่ต้องแก้ schema

## Sources

[`ref/chatgpt-care-agent-design.md`](../ref/chatgpt-care-agent-design.md) §"Medication Memory", §5
