# Care Agent Architecture

> ที่มาทั้งหมด: [`ref/chatgpt-care-agent-design.md`](../ref/chatgpt-care-agent-design.md)
> ข้อผูกพันที่บังคับใช้แล้ว: [`decisions/`](../decisions/)

## สิ่งที่ระบบนี้เป็น

**External Memory & Care Companion** — ไม่ใช่ reminder app และไม่ใช่ chatbot สำหรับผู้สูงอายุ

ระบบทำ 5 อย่าง:

```
1. REMEMBER   จำสิ่งที่ผู้ป่วยลืม        (วันนี้วันอะไร · ยาตัวไหน · หมอคนไหนสั่ง · ของอยู่ที่ไหน)
2. REMIND     เตือนสิ่งที่ต้องทำ          (แบบ closed-loop ไม่ใช่ notification ทิ้ง)
3. RECORD     บันทึกสิ่งผิดปกติ/คำถาม     (ผู้ป่วยพูดธรรมดา ระบบจัดโครงสร้างให้)
4. PREPARE    เตรียมก่อนกิจกรรมสำคัญ     (นัดหมอ ตรวจเลือด เดินทาง)
5. ESCALATE   ส่งต่อคนเมื่อทำไม่ได้        (caregiver → clinical authority)
```

หลักที่ต่างจากระบบเตือนทั่วไป:

> **Don't just remind the patient. Reduce the amount of things the patient has to remember.**

> **Agent ต้องช่วย "ทำให้จบ" ไม่ใช่แค่ "เตือนให้เริ่ม"** — ส่ง reminder แล้ว ≠ งานเสร็จ

## ภาพรวม

```
                          CARE ORCHESTRATOR
                                 │
   ┌──────────┬──────────┬───────┼───────┬──────────┬──────────┐
   ▼          ▼          ▼       ▼       ▼          ▼          ▼
Orientation Routine  Medication Appt   Memory   Activity    Safety
  Agent      Agent     Agent    Agent   Agent     Agent      Agent
   │          │          │       │       │          │          │
 วันนี้      กิจวัตร     ยา     นัด+    journal   งานหลาย    sensor
วันอะไร     อาหาร    version   เตรียม  คำถาม     ขั้นตอน    (M5)
อยู่ไหน     กิจกรรม   ก่อน/หลัง  ตัว    care plan  ของใช้
   │          │        อาหาร     │       │          │          │
   └──────────┴──────────┴───────┼───────┴──────────┴──────────┘
                                 ▼
                       ap_policy  (action_risk → authority)
                                 │
                        ┌────────┴────────┐
                        ▼                 ▼
                   Auto Action      Human Approval
                        │                 │
                        └────────┬────────┘
                                 ▼
                          ap_audit (append-only)
                                 │
                                 ▼
                      Caregiver / Family / Doctor
```

## Closed loop คือหัวใจ

reminder ทุกตัวเป็น **job** ที่มีสถานะ ไม่ใช่ข้อความที่ส่งแล้วจบ

```
ถึงเวลา → JOB_CREATED
   ↓
ส่ง reminder (EXECUTION_STARTED)
   ↓
ผู้ป่วยตอบ? ──yes──→ care.*.confirmed → JOB_COMPLETED
   │ no
   ↓ รอ (grace period ต่อ tenant)
เตือนซ้ำ ครั้งที่ 2, 3 (ตาม policy — ไม่ใช่ spam)
   ↓ ยังไม่ตอบ
ถามตรง ๆ "ทานข้าวแล้วหรือยัง"
   ↓ ยังไม่ตอบ
care.*.missed → GOVERNANCE_DECISION → care.escalated → caregiver
```

**ไม่มีจุดไหนที่ระบบเดาแทนผู้ป่วย** — ไม่มีหลักฐาน = ยังไม่ยืนยัน

## Task Continuity — งานที่เริ่มได้แต่ทำไม่จบ

ปัญหาที่เจอจริง: เอาผ้าเข้าเครื่องแล้วลืมกด start · เครื่องซักเสร็จแล้วลืมเอาไปตาก

```
TASK STATE
NOT_STARTED → STARTING → IN_PROGRESS → WAITING → READY_FOR_NEXT_STEP → COMPLETED
                              ↓                          ↓
                           BLOCKED                   NEEDS_HELP → caregiver
                              ↓
                          ABANDONED
```

งานหนึ่งชิ้น = หลายขั้น แต่ละขั้นมีสถานะของตัวเอง และ **event ภายนอก
(เครื่องซักเสร็จ) ปลุกขั้นถัดไปได้** — engine เดียวกันนี้ใช้กับ "เตรียมตัวไปหาหมอ" ได้ทั้งชุด

## ชั้นของความจำ — แยกกันเด็ดขาด

```
                        CARE MEMORY
   ┌──────────────┬──────────────┬──────────────┬──────────────┐
   ▼              ▼              ▼              ▼              ▼
Daily Memory  Health Journal  Medication    Care Plan    Medical Knowledge
กิจวัตร        อาการ/คำถาม    version chain  หมอสั่งอะไร   ความรู้ทั่วไป
   │              │              │              │              │
   └──── ของผู้ป่วยคนนี้ ────────┘              │              │
                                          ผู้มีอำนาจกำหนด    มีแหล่งอ้างอิง
```

> **Personal Memory ≠ Care Plan ≠ Medical Knowledge ≠ Medical Decision**

ห้าม LLM สร้างข้อมูลใหม่แล้วบันทึกเป็นความทรงจำของผู้ป่วยโดยอัตโนมัติ
ทุกสิ่งที่สำคัญต้องมี `source` + `timestamp` + `version` + `audit`

## Orientation — ไม่ใช่ edge case

"ตื่นมาไม่รู้วันไหน" เป็น scenario หลักที่ต้องมี automated test ตั้งแต่ MVP
5 ชั้น: **TIME · DATE · PLACE · PERSON · PLAN**
ถามซ้ำกี่ครั้งก็ตอบเหมือนเดิม โดยไม่ทำให้ผู้ป่วยรู้สึกผิด

## ขอบเขตที่ห้ามข้าม

| ระบบทำ | ระบบไม่ทำ |
|---|---|
| "วันนี้ยังไม่มีบันทึกว่าทานยาเช้า" | "ผู้ป่วยมีอาการแย่ลง" |
| "กิจวัตรวันนี้ต่างจาก pattern ปกติ" | "ภาวะสมองเสื่อมกำลังแย่ลง" |
| "เอกสารโรงพยาบาลระบุข้อกำหนดเรื่องอาหารก่อนตรวจ" | เดาเองว่าต้อง fasting กี่ชั่วโมง |
| เสนอให้คนยืนยันการเปลี่ยนยา | เปลี่ยนยาเอง |
| "ยังไม่มีข้อมูลว่าทานแล้ว" | เดาว่าน่าจะทานแล้วเพราะปกติทานตอนนี้ |

## เอกสารที่เกี่ยวข้อง

- [`team-plan.md`](team-plan.md) — ใครทำอะไร milestone ไหน
- [`risk-model.md`](risk-model.md) — risk / authority / escalation
- [`patient-lifecycle.md`](patient-lifecycle.md) — ตั้งแต่สร้างผู้ป่วยจนถึง daily loop
- [`stack.md`](stack.md) — stack และเหตุผล
