# ออกแบบเอเจนต์ดูแลผู้ป่วย

Source: https://chatgpt.com/share/6a84445b-8120-83ec-ae66-88ce01a412fb


---

## USER

Original custom instructions no longer available


---

## USER

@GitHub https://github.com/monthop-gmail/agent-platform แนวคิดนี้ ถ้าจะเอามาทำ agent เพื่อดูแลผู้ป่วยที่เริ่มมีสภาวะสมองเสื่อม ลืมกิจวัตรประจำวัน ลืมทานข้าว ทานยา หาหมอ และก็อยากให้ผู้ป่วยคนอื่นๆเอาไปใช้ด้วย


---

## ASSISTANT

The output of this plugin was redacted.


---

## TOOL

The output of this plugin was redacted.


---

## ASSISTANT

The output of this plugin was redacted.


---

## TOOL

The output of this plugin was redacted.


---

## ASSISTANT

The output of this plugin was redacted.


---

## TOOL

The output of this plugin was redacted.


---

## ASSISTANT

The output of this plugin was redacted.


---

## TOOL

The output of this plugin was redacted.


---

## ASSISTANT

ได้เลยจร้า และจริง ๆ **แนวคิดนี้เข้ากับ `agent-platform` มาก** เพราะ repo ปัจจุบันถูกวางเป็น foundation สำหรับสร้าง agent หลายประเภทอยู่แล้ว ไม่ควรเอา logic ผู้ป่วยไปยัดใน core โดยตรง แต่ทำเป็น **Healthcare / Elder Care Agent เป็น consumer ของ platform** จะสวยกว่า fileciteturn1file0L2-L5

จาก architecture ปัจจุบันที่แยก Identity / Gateway / Runtime / Workflow / Policy และให้ Tools/MCP/Sandbox เป็นทางผ่านไปยังระบบจริงอยู่แล้ว ถือว่าเหมาะมากกับ use case นี้ fileciteturn3file0L2-L2

### ผมมองเป็น “AI Caregiver Agent” มากกว่า “Dementia Agent”

เพราะไม่ควรผูกระบบกับโรคสมองเสื่อมโดยตรง แต่สร้างเป็น **Personal Care Agent** ที่ปรับ profile ตามผู้ใช้ได้

```text
                    AGENT PLATFORM
                          │
                 Care Agent Runtime
                          │
              ┌───────────┼───────────┐
              │           │           │
          Routine       Health      Safety
           Agent        Agent       Agent
              │           │           │
              └───────────┼───────────┘
                          │
                    Care Orchestrator
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   Patient App       Caregiver App      Family App
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │
              Hospital / Clinic / Pharmacy
```

### สิ่งที่ Agent ควรทำ

**1. Daily Routine Agent**

รู้ว่าแต่ละคนมี routine อะไร เช่น

- 07:00 ตื่น
- 07:30 อาหารเช้า
- 08:00 ยา
- 10:00 เดินเล่น
- 12:00 อาหารกลางวัน
- 14:00 พัก
- 17:00 อาหารเย็น
- 20:00 ยา
- 21:00 เข้านอน

ไม่ใช่แค่ notification แต่เป็น **closed-loop reminder**

> “ถึงเวลาทานข้าวแล้วนะครับ”

ถ้าไม่ตอบ → เตือนอีกครั้ง  
ถ้ายังไม่ตอบ → ถามว่า

> “ทานข้าวแล้วหรือยังครับ?”

ถ้ายังไม่สำเร็จ → แจ้ง caregiver

---

**2. Medication Agent**

อันนี้ควรทำเป็นระบบที่ conservative มาก ๆ

Agent สามารถ:

- เตือนเวลา
- ถามว่าทานยาแล้วหรือยัง
- บันทึก response
- แจ้ง caregiver ถ้าพลาด
- แจ้งเตือน refill
- เตือนวันนัดแพทย์

แต่ **ไม่ควรให้ LLM ตัดสินใจเปลี่ยนยา / ปริมาณยา / หยุดยาเอง**

ให้ medical authority อยู่ที่แพทย์/ผู้ดูแล ส่วน Agent เป็น **execution + monitoring layer**

ซึ่งตรงกับหลักใน `agent-platform` ที่วางไว้ว่า Agent ไม่ควรเป็น authority และการแตะระบบจริงต้องผ่าน tools/policy layer fileciteturn3file0L2-L2

---

### 3. Memory Agent

อันนี้ผมว่าเป็น killer feature เลย

ผู้ป่วยสามารถถาม:

> “วันนี้ต้องไปไหนนะ?”

Agent:

> “วันนี้มีนัดคุณหมอเวลา 14:00 ครับ ผมจะเตือนอีกครั้งตอน 13:00”

หรือ

> “ยานี้กินหรือยัง?”

Agent ตรวจจาก event จริง ไม่เดา

หรือ

> “ลูกสาวชื่ออะไรนะ?”

Agent สามารถช่วย recall ข้อมูลที่ผู้ดูแลอนุญาตให้เก็บได้

แต่ต้องแยกชัดเจนระหว่าง

**Memory ที่ผู้ใช้บันทึกไว้**  
กับ  
**สิ่งที่ AI คาดเดา**

ห้ามให้ hallucination กลายเป็น “ความทรงจำของผู้ป่วย”

---

### 4. Behavior / Anomaly Agent

นี่จะทำให้ระบบก้าวจาก “แอปเตือน” → “AI caregiver”

เช่นระบบเรียนรู้ว่า

```text
ปกติ
07:30 breakfast
08:00 medicine
09:00 walking

วันนี้
08:30 ยังไม่กินอาหาร
09:00 ยังไม่กินยา
10:30 ยังไม่ออกจากบ้าน
```

Agent จึงสามารถสร้าง event:

```text
CARE_PATTERN_DEVIATION
severity: medium
```

แล้วให้ caregiver ตรวจสอบ

ไม่ควรบอกทันทีว่า

> “ผู้ป่วยมีอาการ dementia แย่ลง”

แต่ควรบอกว่า

> “วันนี้กิจวัตรแตกต่างจาก pattern ปกติ”

นี่สำคัญมาก

---

### 5. Safety Agent

ต่อยอดได้ไกลมาก

เช่น

- ออกจากบ้านผิดเวลา
- เดินออกนอกพื้นที่ปลอดภัย
- ไม่กลับบ้าน
- ล้ม
- ไม่ตอบสนอง
- เปิดเตา
- ประตูเปิดค้าง
- อยู่ในห้องน้ำนานผิดปกติ

ถ้ามี IoT / camera / smartwatch / phone GPS ก็เอาเข้ามาเป็น event ได้

```text
Camera
GPS
Wearable
Door sensor
Motion sensor
Smart pill box
Smart speaker
        │
        ▼
     Event Bus
        │
        ▼
   Care Agent
```

---

## และที่สำคัญ: ทำให้ใช้กับ “ผู้ป่วยทุกคน” ได้

ไม่ควรสร้าง

> Dementia Agent

แต่สร้าง

> **Care Agent Platform**

แล้ว profile เป็น configuration

```yaml
care_profile:
  routine:
    enabled: true

  medication:
    enabled: true

  appointment:
    enabled: true

  nutrition:
    enabled: true

  safety:
    enabled: true

  memory_assistance:
    enabled: true

  caregiver_escalation:
    enabled: true
```

คนหนึ่งอาจเปิดเฉพาะ:

```text
Medication
Appointment
```

อีกคน:

```text
Routine
Medication
Nutrition
Safety
```

อีกคนอาจเป็นผู้สูงอายุที่ไม่ได้มี dementia เลย ก็ใช้ได้

---

# ผมแนะนำแยก repo

อย่าเอาเข้า `agent-platform` โดยตรง

ให้ architecture เป็น:

```text
agent-platform
       │
       ├── identity
       ├── gateway
       ├── runtime
       ├── workflow
       ├── policy
       ├── capability
       └── contracts
              │
              ▼
       care-agent-platform
              │
       ├── care-orchestrator
       ├── routine-agent
       ├── medication-agent
       ├── appointment-agent
       ├── memory-agent
       ├── safety-agent
       ├── nutrition-agent
       └── caregiver-agent
              │
              ▼
       Healthcare Connectors
              │
       ├── Hospital
       ├── Clinic
       ├── Pharmacy
       ├── Odoo
       ├── IoT
       ├── Wearables
       └── Family Apps
```

**`agent-platform` = engine/platform**

**`care-agent-platform` = domain implementation**

แบบนี้อนาคตสามารถสร้าง:

```text
agent-platform
       │
       ├── care-agent-platform
       ├── security-agent-platform
       ├── agriculture-agent-platform
       ├── enterprise-agent-platform
       ├── education-agent-platform
       └── maritime-agent-platform
```

ได้โดยไม่ทำให้ core พัง

---

## และผมว่ามีอีกชั้นที่ควรเพิ่ม

จากที่เราคุยกันก่อนหน้านี้เรื่อง Knowledge/RAG ผมจะทำ:

```text
                Care Agent
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
    Patient Memory       Medical Knowledge
          │                   │
          ▼                   ▼
      Personal RAG       Clinical RAG
```

**Personal RAG**

รู้เฉพาะสิ่งของผู้ป่วย:

- ตารางชีวิต
- ยา
- นัดหมาย
- คนในครอบครัว
- preference
- ประวัติ interaction

**Medical Knowledge**

เป็น knowledge ที่มีแหล่งอ้างอิงและ governance แยกต่างหาก

แล้วกำหนด policy ว่า

> Personal memory ≠ Medical knowledge ≠ Medical decision

อันนี้จะทำให้ระบบปลอดภัยขึ้นเยอะ

---

# MVP ที่ผมแนะนำ

อย่าเริ่มจาก camera / wearable / diagnosis ก่อน

ทำแค่:

```text
Patient
  │
  ▼
Care Agent
  │
  ├── Daily Routine
  ├── Food Reminder
  ├── Medication Reminder
  ├── Appointment Reminder
  └── Caregiver Escalation
```

มี 3 interface:

```text
Patient
   │
   └── Voice / LINE / Mobile

Caregiver
   │
   └── Dashboard

Doctor
   │
   └── Read-only / authorized clinical view
```

แล้วทดสอบ closed-loop:

```text
Reminder
   ↓
Patient response
   ↓
Confirmed?
 ┌─┴─┐
YES  NO
 │    │
Done  Retry
      ↓
   Escalate
      ↓
 Caregiver
```

นี่จะเป็น PoC ที่ **วัดผลได้จริง** มากกว่าเริ่มด้วย multi-agent ใหญ่ ๆ

### ชื่อ repo ที่ผมชอบ

**`care-agent-platform`**

หรือถ้าต้องการชื่อ product ที่เป็นมิตรกับผู้สูงอายุ:

**`care-companion`**

แต่ architecture-level ผมเชียร์ `care-agent-platform` เพราะมันสอดคล้องกับ `agent-platform` และสามารถรองรับผู้ป่วยหลายประเภทได้ตั้งแต่แรก

และจุดสำคัญที่สุดคือ **อย่าให้ AI ทำหน้าที่เป็นหมอ** — ให้เป็น “ผู้ช่วยดูแล + เฝ้าระวัง + ประสานงาน + escalation” โดยมีคน/ระบบที่มีอำนาจตัดสินใจอยู่เหนือ Agent เสมอ ซึ่งเข้ากับ governance boundary ของ `agent-platform` ที่มีอยู่แล้วมากครับ fileciteturn3file0L2-L2

ถ้าจะเดินต่อ ผมมองว่าโปรเจกต์นี้ **ควรเป็นหนึ่งใน consumer ตัวแรก ๆ ของ `agent-platform` เลย** เพราะจะบังคับให้ platform พิสูจน์เรื่อง identity, memory, workflow, policy, event, approval และ multi-tenancy ในสถานการณ์จริงได้ครบมาก.


---

## USER

ขอภาพรวมและแนวทาง เพื่อส่งทีมงาน implement จร้า


---

## ASSISTANT

ได้เลยจร้า อันนี้ผมแนะนำให้ส่งทีมเป็น **blueprint ระดับ repo + implementation roadmap** โดยยึด `agent-platform` เป็น foundation และสร้าง `care-agent-platform` เป็น domain consumer ไม่ควรเอา healthcare logic เข้า core โดยตรง เพราะ architecture ปัจจุบันของ `agent-platform` วาง contract, identity, gateway, runtime, workflow, policy และ capability routing ไว้เป็น platform layer อยู่แล้ว fileciteturn3file0L2-L2

:::writing{variant="document" id="58321" title="Care Agent Platform — Implementation Blueprint"}
# Care Agent Platform — Implementation Blueprint

## 1. เป้าหมาย

สร้าง **AI Care Agent Platform** สำหรับช่วยดูแลผู้สูงอายุ ผู้ที่เริ่มมีปัญหาด้านความจำ และผู้ป่วยที่ต้องการความช่วยเหลือด้านกิจวัตรประจำวัน

ระบบต้องไม่ทำหน้าที่แทนแพทย์ แต่เป็น:

- Personal Care Assistant
- Daily Routine Assistant
- Medication Reminder
- Appointment Assistant
- Memory Assistant
- Safety Monitor
- Caregiver Coordinator
- Escalation Agent

Platform ต้องออกแบบให้ผู้ป่วยหลายคน/หลายครอบครัวสามารถใช้งานร่วมกันได้แบบ multi-tenant

---

# 2. Repository Strategy

ใช้ architecture:

```text
agent-platform
       │
       │ platform contracts / runtime / policy
       ▼
care-agent-platform
       │
       ├── care orchestration
       ├── patient profile
       ├── routine
       ├── medication
       ├── appointment
       ├── nutrition
       ├── memory
       ├── safety
       ├── caregiver
       └── escalation
```

หลักการ:

> `agent-platform` = generic agent infrastructure

> `care-agent-platform` = healthcare / elder-care domain implementation

ห้ามนำ business logic ของ Care Agent ไปผูกกับ core ของ `agent-platform`

---

# 3. Core Architecture

```text
                    CARE AGENT PLATFORM
                            │
                 ┌──────────┴──────────┐
                 │   Care Orchestrator │
                 └──────────┬──────────┘
                            │
       ┌────────────────────┼────────────────────┐
       ▼                    ▼                    ▼
   Routine Agent       Health Agent         Safety Agent
       │                    │                    │
       ├─ Food              ├─ Medication        ├─ Location
       ├─ Sleep             ├─ Appointment       ├─ Fall
       ├─ Activity          └─ Health events     ├─ Door
       └─ Daily routine                          └─ Abnormal pattern
                            │
                            ▼
                     Policy / Risk Engine
                            │
                    ┌───────┴────────┐
                    ▼                ▼
               Auto Action       Human Approval
                    │                │
                    └───────┬────────┘
                            ▼
                    Caregiver / Family
```

---

# 4. Agents

## 4.1 Routine Agent

ดูแลกิจวัตรประจำวัน

ตัวอย่าง:

```text
07:00 wake up
07:30 breakfast
08:00 medication
10:00 activity
12:00 lunch
14:00 rest
17:00 dinner
20:00 medication
21:00 sleep
```

ต้องรองรับ:

- schedule
- recurring routine
- reminder
- confirmation
- missed routine
- retry
- escalation

---

# 5. Medication Agent

หน้าที่:

- เตือนเวลาทานยา
- ตรวจว่าผู้ป่วย acknowledge หรือไม่
- บันทึก medication event
- แจ้ง caregiver เมื่อพลาด
- แจ้ง refill reminder
- เชื่อม appointment

ห้าม Agent:

- เปลี่ยนยาเอง
- เพิ่ม/ลด dosage
- หยุดยา
- วินิจฉัยโรค
- สั่งการรักษา

การตัดสินใจทางการแพทย์ต้องมี authorized human / clinical system เป็น authority

---

# 6. Appointment Agent

จัดการ:

- นัดแพทย์
- เตือนล่วงหน้า
- เตือนเวลาเดินทาง
- confirm appointment
- missed appointment
- follow-up
- caregiver notification

ตัวอย่าง:

```text
Appointment
     ↓
24h reminder
     ↓
2h reminder
     ↓
Patient confirmation
     ↓
Travel reminder
     ↓
Appointment completed?
```

---

# 7. Memory Agent

เป็น Personal Memory Assistant

เก็บเฉพาะข้อมูลที่ได้รับอนุญาต เช่น:

- ชื่อสมาชิกครอบครัว
- ตารางชีวิต
- สถานที่สำคัญ
- สิ่งที่ผู้ป่วยชอบ
- routine
- appointment
- caregiver
- interaction history

ต้องแยก:

```text
Personal Memory
Medical Knowledge
Medical Decision
```

ออกจากกันอย่างชัดเจน

ห้าม LLM สร้างข้อมูลใหม่แล้วบันทึกเป็นความทรงจำโดยอัตโนมัติ

---

# 8. Safety Agent

รับ event จาก:

- mobile
- GPS
- wearable
- smart watch
- IoT
- door sensor
- motion sensor
- camera/VMS
- emergency button

ตัวอย่าง:

```text
Normal pattern
      │
      ▼
Deviation detected
      │
      ▼
Risk classification
      │
 ┌────┼────┐
 ▼    ▼    ▼
Low Medium High
 │     │     │
log  caregiver emergency flow
```

ระบบต้องแยก:

**Observation ≠ Diagnosis**

เช่น:

> "ผู้ป่วยยังไม่ออกจากห้อง 3 ชั่วโมง"

ไม่ใช่:

> "ผู้ป่วยมีภาวะผิดปกติ"

---

# 9. Behavior / Pattern Agent

เรียนรู้ baseline ของแต่ละคน

ตัวอย่าง:

```text
Normal:
08:00 medication
08:30 breakfast
09:00 walking

Today:
09:00 medication missed
10:00 breakfast missed
11:00 no activity
```

Agent สร้าง:

```yaml
event:
  type: routine_deviation
  severity: medium
  confidence: 0.91
```

ไม่ควรสรุป diagnosis

แต่สามารถ trigger:

```text
Patient reminder
       ↓
Retry
       ↓
Caregiver notification
```

---

# 10. Caregiver Agent

เป็น bridge ระหว่าง Patient กับครอบครัว/ผู้ดูแล

รองรับ:

- notification
- escalation
- daily summary
- missed medication
- missed meal
- appointment
- abnormal routine
- safety event

ตัวอย่าง Daily Summary:

```text
วันนี้

อาหาร       2/3
ยา          3/3
กิจกรรม     2/2
นัดหมาย     1/1
Safety      ปกติ

ต้องติดตาม:
- มื้อกลางวันล่าช้า 45 นาที
```

---

# 11. Care Orchestrator

ไม่ให้แต่ละ Agent ทำงานแยกกันแบบ uncontrolled

ให้มี orchestration:

```text
Event
  ↓
Context
  ↓
Policy
  ↓
Capability Routing
  ↓
Agent
  ↓
Action
  ↓
Verification
  ↓
Escalation
```

ตัวอย่าง:

```text
Medication due
      ↓
Medication Agent
      ↓
reminder
      ↓
patient response?
   ┌──┴──┐
  yes    no
   │      │
 done   retry
          ↓
       timeout
          ↓
     caregiver
```

---

# 12. Risk & Approval Model

แบ่ง risk อย่างน้อย:

```text
LOW
MEDIUM
HIGH
CRITICAL
```

ตัวอย่าง:

### LOW

- routine reminder
- meal reminder
- appointment reminder

### MEDIUM

- missed medication
- repeated missed meals
- abnormal routine

### HIGH

- possible fall
- wandering
- repeated medication failure

### CRITICAL

- emergency event
- severe safety event

หลัก:

> AI สามารถ recommend/action ได้เฉพาะ capability ที่ policy อนุญาต

> AI ไม่มี medical authority

> High-risk action ต้องมี escalation / human approval ตาม policy

---

# 13. Multi-Tenant Model

ต้องรองรับ:

```text
Tenant
 ├── Organization
 ├── Care Team
 ├── Caregiver
 ├── Patient
 └── Devices
```

ตัวอย่าง:

```text
Hospital A
 ├── Patient 001
 ├── Patient 002
 └── Patient 003

Family B
 └── Patient 004
      ├── Daughter
      ├── Son
      └── Nurse
```

ข้อมูลของ tenant ห้ามข้ามกัน

---

# 14. Identity & Consent

ต้องมี relationship:

```text
Patient
  │
  ├── Caregiver
  ├── Family
  ├── Doctor
  └── Organization
```

พร้อม consent:

```text
who
  ↓
can access
  ↓
which data
  ↓
for what purpose
  ↓
for how long
```

เช่น:

```text
Daughter
  ├── routine       READ
  ├── medication   READ
  ├── location     READ
  └── medical      LIMITED

Doctor
  └── clinical data READ
```

---

# 15. Personal Memory / RAG

แบ่งเป็น 3 ชั้น:

```text
                    Knowledge
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    Patient Memory  Care Plan   Medical Knowledge
```

### Patient Memory

ข้อมูลเฉพาะบุคคล

### Care Plan

สิ่งที่ caregiver/clinical authority กำหนด

### Medical Knowledge

ความรู้ทางการแพทย์จากแหล่งที่ได้รับอนุญาต

Agent ต้องระบุ provenance ของข้อมูลสำคัญ

---

# 16. Event Architecture

ทุก action ควรกลายเป็น event

```text
patient.reminder.sent
patient.reminder.acknowledged
patient.reminder.missed

meal.reminder.sent
meal.confirmed
meal.missed

medication.reminder.sent
medication.confirmed
medication.missed

appointment.created
appointment.reminded
appointment.completed

safety.event.detected
safety.event.acknowledged
caregiver.notified
```

Event ต้องมี:

```yaml
tenant_id
patient_id
actor_id
event_type
timestamp
source
confidence
risk
policy_decision
correlation_id
```

---

# 17. Audit

ต้อง audit ทุก action:

```text
Who
What
When
Why
Source
Policy
Agent
Model
Tool
Result
```

โดยเฉพาะ healthcare-related actions

ต้องสามารถตอบย้อนหลังได้ว่า:

> ทำไม Agent ถึงส่ง notification นี้?

> ข้อมูลอะไรถูกใช้?

> Policy ไหนอนุญาต?

> Agent ตัวไหนตัดสินใจ?

---

# 18. External Integrations

ออกแบบเป็น connectors ผ่าน platform boundary

```text
Care Agent
    │
    ▼
Capability / Tool Layer
    │
 ┌──┼───────────────┐
 ▼  ▼               ▼
Odoo Hospital      IoT
     │              │
   Clinic         Wearable
     │              │
 Pharmacy        Camera/VMS
```

Agent ห้าม access backend โดยตรง

ใช้ MCP / Tool / Connector abstraction ตาม contract ของ `agent-platform`

---

# 19. User Interfaces

MVP ให้มี 3 interface

## Patient

เน้นง่ายมาก:

```text
วันนี้

🍚 ทานข้าว
💊 ทานยา
🏥 นัดหมอ
🚶 กิจกรรม
```

ควร support:

- voice
- large buttons
- LINE
- mobile
- smart speaker ในอนาคต

## Caregiver

Dashboard:

```text
Patients
Risk
Medication
Routine
Appointments
Alerts
Daily Summary
```

## Clinical / Professional

Read-only หรือ permission-based:

```text
Patient timeline
Care events
Medication adherence
Appointment history
Risk events
```

ไม่ให้ Agent เขียน clinical decision โดยพลการ

---

# 20. MVP

อย่าเริ่มด้วยทุกอย่าง

Phase 1:

```text
Patient
  │
  ▼
Care Agent
  ├── Routine
  ├── Meal Reminder
  ├── Medication Reminder
  ├── Appointment
  └── Caregiver Escalation
```

ใช้ข้อมูลจำลองก่อน

ต้องสามารถ run ด้วย:

```bash
docker compose up
```

และมี demo scenario:

```text
07:30 breakfast
08:00 medication
12:00 lunch
14:00 appointment
20:00 medication
```

ทดสอบ:

```text
Patient confirms
Patient ignores
Patient misses
Caregiver notified
```

---

# 21. Phase 2

เพิ่ม:

- Personal Memory
- Voice interaction
- LINE
- caregiver dashboard
- daily summary
- behavior baseline
- pattern deviation
- notification policy
- consent
- audit

---

# 22. Phase 3

เพิ่ม:

- wearable
- GPS
- smart home
- IoT
- camera/VMS
- fall detection
- wandering detection
- hospital integration
- pharmacy integration

---

# 23. Phase 4

เพิ่ม multi-organization platform:

```text
Family
Clinic
Hospital
Nursing Home
Home Care
```

และสามารถ provision Care Agent ใหม่ให้ผู้ป่วยแต่ละคนได้

```text
Create Patient
      ↓
Care Profile
      ↓
Routine
      ↓
Medication
      ↓
Caregiver
      ↓
Policy
      ↓
Deploy Care Agent
```

---

# 24. Repository Structure

เสนอ:

```text
care-agent-platform/
├── README.md
├── architecture/
│   ├── platform-architecture.md
│   ├── care-agent-architecture.md
│   ├── patient-lifecycle.md
│   └── risk-model.md
│
├── contracts/
│   ├── patient/
│   ├── caregiver/
│   ├── routine/
│   ├── medication/
│   ├── appointment/
│   ├── safety/
│   ├── memory/
│   ├── consent/
│   └── escalation/
│
├── agents/
│   ├── care-orchestrator/
│   ├── routine-agent/
│   ├── medication-agent/
│   ├── appointment-agent/
│   ├── memory-agent/
│   ├── safety-agent/
│   └── caregiver-agent/
│
├── policies/
│   ├── risk/
│   ├── consent/
│   ├── escalation/
│   └── action/
│
├── connectors/
│   ├── notification/
│   ├── healthcare/
│   ├── odoo/
│   ├── iot/
│   └── wearable/
│
├── apps/
│   ├── patient/
│   ├── caregiver/
│   └── clinical/
│
├── tests/
├── examples/
├── docker-compose.yml
└── docs/
```

---

# 25. Testing Strategy

ต้องเน้น scenario testing มากกว่าแค่ unit test

ตัวอย่าง:

```text
Scenario:
Patient misses medication

Expected:
1. Reminder sent
2. No confirmation
3. Retry
4. Timeout
5. Caregiver notification
6. Audit event created
```

รวมถึง adversarial tests:

```text
LLM hallucination
wrong patient
wrong medication
duplicate reminder
stale memory
unauthorized access
cross-tenant access
false safety alert
agent loop
notification storm
```

---

# 26. Definition of Done สำหรับ MVP

MVP ถือว่าสำเร็จเมื่อ:

- [ ] สร้าง Patient ได้
- [ ] สร้าง Caregiver ได้
- [ ] กำหนด routine ได้
- [ ] กำหนด medication reminder ได้
- [ ] กำหนด appointment ได้
- [ ] Agent ส่ง reminder ได้
- [ ] Patient acknowledge ได้
- [ ] Missed event ถูกตรวจพบ
- [ ] Escalation ไป caregiver ได้
- [ ] ทุก event มี audit trail
- [ ] Multi-tenant isolation ทำงาน
- [ ] Policy จำกัด action ของ Agent
- [ ] ไม่มี medical diagnosis/action ที่ไม่ได้รับอนุญาต
- [ ] Docker Compose สามารถรัน PoC ได้
- [ ] มี automated scenario tests
- [ ] เชื่อมกับ `agent-platform` ผ่าน contract ที่กำหนด
- [ ] สามารถสร้าง Care Agent หลาย patient โดยใช้ platform เดียวกัน

---

# 27. หลักการสำคัญที่สุด

ทีมต้องยึด 7 ข้อนี้:

1. **AI ≠ Doctor**
2. **AI ≠ Authority**
3. **Observation ≠ Diagnosis**
4. **Personal Memory ≠ Medical Truth**
5. **High-risk action ต้องมี governance**
6. **ทุก action ต้อง audit ได้**
7. **Patient data ต้อง tenant/consent aware**

เป้าหมายไม่ใช่สร้าง chatbot สำหรับผู้สูงอายุ

แต่คือ:

```text
                 CARE AGENT
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
    Remember      Remind        Observe
       │             │             │
       └─────────────┼─────────────┘
                     ▼
                  Assist
                     │
                     ▼
                 Escalate
                     │
                     ▼
              Human Caregiver
                     │
                     ▼
              Clinical Authority
```

**AI ทำหน้าที่ช่วยให้คนดูแลผู้ป่วยได้ดีขึ้น ไม่ใช่แทนที่คนดูแลหรือแพทย์**

---

# 28. งานสำหรับทีม

เริ่มจาก Milestone ตามลำดับ:

### M1 — Foundation

- [ ] สร้าง `care-agent-platform`
- [ ] เชื่อม `agent-platform`
- [ ] กำหนด contracts
- [ ] patient/caregiver identity
- [ ] tenant isolation
- [ ] audit/event model

### M2 — Care Loop

- [ ] Routine Agent
- [ ] Medication Agent
- [ ] Appointment Agent
- [ ] Notification
- [ ] Patient acknowledgement
- [ ] Missed-event detection

### M3 — Escalation

- [ ] Caregiver Agent
- [ ] Risk policy
- [ ] escalation workflow
- [ ] approval boundary
- [daily summary

### M4 — Intelligence

- [ ] Personal Memory
- [ ] RAG
- [ ] behavior baseline
- [ ] routine deviation
- [ ] conversational interface

### M5 — Safety

- [ ] IoT connector
- [ ] GPS
- [wearable]
- [camera/VMS]
- [safety events
- [high-risk escalation]

### M6 — Platform

- [ ] multi-organization
- [ ] clinic/hospital integration
- [pharmacy integration
- [care plan
- [consent management
- [compliance/audit hardening]

ทุก milestone ให้ใช้ GitHub Issues และ PRs ตาม workflow ของ `agent-platform` และทุก architectural decision ที่เปลี่ยน platform boundary ให้ทำ ADR ก่อน implement
:::


---

## USER

บางครั้งมีอาการผิดปกติ หรือข้อสงสัย ก็อยากบันทึก เวลาถึงวันนัดหมอ ก็จะได้ไม่ลืม หมอก็มีหลายคน มีเรื่องต้องจำเยอะ แต่ก็ลืมง่ายเพราะสมองเสื่อม


---

## ASSISTANT

ใช่เลยจร้า และนี่ทำให้ผมมองว่า **Care Agent ควรมี “Patient Journal / Health Memory” เป็น core feature ตั้งแต่ MVP** ไม่ใช่แค่ระบบเตือนยา/นัดหมอ

เพราะปัญหาจริงของผู้ที่เริ่มมีภาวะความจำเสื่อมคือ **ไม่ได้ลืมเฉพาะกิจวัตร แต่ลืมสิ่งที่เกิดขึ้นระหว่างวันและลืมว่าจะต้องถามอะไรหมอ** ด้วย

### Flow ที่ควรเป็น

```text
ผู้ป่วยรู้สึกผิดปกติ
        │
        ▼
พูดกับ Care Agent
"ช่วงนี้เดินแล้วรู้สึกเวียนหัว"
        │
        ▼
Agent บันทึกทันที
        │
        ├── เวลา
        ├── อาการ
        ├── สิ่งที่เกิดขึ้นก่อนหน้า
        ├── ระดับความรุนแรง (ถ้าผู้ป่วยระบุ)
        └── รูปภาพ/เสียง (ถ้ามี)
        │
        ▼
Patient Health Journal
        │
        ├── Doctor A
        ├── Doctor B
        ├── Doctor C
        └── นัดหมายครั้งถัดไป
                │
                ▼
        Appointment Preparation
                │
                ▼
        "สิ่งที่ควรแจ้ง/ถามคุณหมอ"
```

จุดสำคัญคือ **ผู้ป่วยไม่ต้องจำว่าจะต้องบันทึกอย่างไร**

พูดธรรมดาได้เลย เช่น

> “เมื่อเช้าปัสสาวะสีเข้มกว่าปกติ”

Agent ควรตอบประมาณ:

> “บันทึกไว้ให้แล้วครับ เกิดวันนี้ช่วงเช้า ต้องการเพิ่มรายละเอียดไหมครับ?”

ถ้าไม่ต้องการก็จบ ไม่ควรถามเยอะจนผู้ป่วยรำคาญ

---

## แล้วก่อนพบหมอ Agent ทำหน้าที่เป็น “ผู้ช่วยเตรียมตัว”

สมมติผู้ป่วยมีหมอ 4 คน:

```text
หมอหัวใจ
หมอประสาท
หมอไต
หมอทั่วไป
```

Agent รู้ว่าแต่ละ appointment เป็นของใคร

ก่อนวันนัด:

```text
นัดหมอประสาท
       │
       ▼
ค้น Health Journal
       │
       ├── อาการที่บันทึก
       ├── คำถามที่ผู้ป่วยสงสัย
       ├── medication events
       ├── abnormal events
       └── previous appointment notes
       │
       ▼
Doctor Visit Brief
```

เช่น:

> **เตรียมตัวพบนักประสาท 20 ส.ค.**
>
> สิ่งที่บันทึกไว้ตั้งแต่ครั้งล่าสุด:
> - เดินแล้วรู้สึกเวียนหัว 2 ครั้ง
> - ลืมว่าวางกุญแจไว้ที่ไหน 3 ครั้ง
> - เมื่อวันที่ 18 ส.ค. ลืมทานยาช่วงเช้า
>
> คำถามที่เคยบันทึก:
> - อาการเวียนหัวเกี่ยวข้องกับยาหรือไม่?
> - ควรทำอย่างไรเมื่อจำไม่ได้ว่าทานยาแล้วหรือยัง?

**นี่มีค่ามากกว่าการเตือนนัดเฉย ๆ**

---

# ผมจะแยก Memory ออกเป็น 4 ประเภท

```text
                    CARE MEMORY
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   Daily Memory     Health Journal    Appointment
        │                │                │
   กิจวัตรทั่วไป       อาการ/เหตุการณ์      นัดหมอ
        │                │                │
        └────────────────┼────────────────┘
                         ▼
                   Care Plan Memory
```

และเพิ่ม **Question Memory**

```text
Health Journal
      +
Question Memory
      +
Appointment
      ↓
Doctor Visit Brief
```

---

## “คำถามที่อยากถามหมอ” สำคัญมาก

ผู้ป่วยอาจนึกขึ้นมาในวันที่ 10:

> “สงสัยว่ายาตัวนี้ทำให้ง่วงหรือเปล่า”

ก็บอก Agent ได้ทันที:

> “จดไว้ถามหมอครั้งหน้าให้หน่อย”

Agent บันทึก:

```yaml
type: doctor_question
question: "ยาตัวนี้ทำให้ง่วงหรือไม่?"
created_at: ...
target_doctor: neurologist
status: pending
```

ถึงวันนัด Agent เอากลับมาให้ดู

และหลังพบหมอ:

```text
Question
   ↓
Doctor answer
   ↓
Patient / caregiver confirms
   ↓
Save as visit note
```

ตรงนี้จะกลายเป็น **longitudinal care memory** ที่มีประโยชน์มาก

---

# อีกเรื่องที่ควรมี: “เรื่องที่เกิดขึ้นแต่ยังไม่รู้ว่าเกี่ยวกับอะไร”

ไม่ควรบังคับให้ผู้ป่วยเลือกหมอหรือเลือกโรคตอนบันทึก

พูดแค่:

> “ช่วงนี้รู้สึกมือสั่นตอนเช้า”

Agent บันทึกเป็น:

```text
Observation
  status = unclassified
```

แล้วเมื่อมี appointment หลายคน:

```text
Observation
      │
      ├── Neurologist → potentially relevant
      ├── GP         → potentially relevant
      └── Other      → maybe not relevant
```

แต่ **Agent ไม่วินิจฉัยเอง**

มันเพียงช่วยจัดข้อมูลให้คนที่มีหน้าที่ตัดสินใจ

---

# ทำให้เป็น “สมองภายนอก” ของผู้ป่วย

ผมคิดว่า concept ของโปรเจกต์ควรเปลี่ยนจาก

> AI ที่คอยเตือนผู้ป่วย

เป็น

> **AI External Memory & Care Companion**

เพราะมันช่วย 4 เรื่อง:

```text
จำให้
  │
  ├── วันนี้ต้องทำอะไร
  ├── ทานยาแล้วหรือยัง
  ├── นัดหมอเมื่อไร
  └── ใครเป็นหมออะไร
        │
        ▼
บันทึกให้
  │
  ├── อาการ
  ├── เหตุการณ์
  ├── คำถาม
  └── ความกังวล
        │
        ▼
เตรียมให้
  │
  ├── ก่อนพบหมอ
  ├── ก่อนทานยา
  └── ก่อนทำกิจกรรม
        │
        ▼
ประสานให้
  │
  ├── ผู้ป่วย
  ├── ครอบครัว
  ├── caregiver
  └── แพทย์
```

### และผมแนะนำให้เพิ่มสิ่งนี้เข้า blueprint เดิมทันที

**`Patient Health Journal + Doctor Visit Preparation` ควรเป็น M2 ไม่ใช่ feature ระยะท้าย**

เพราะมันเป็นหัวใจของ use case “**ลืมง่าย แต่ยังต้องใช้ชีวิตและรักษาต่อเนื่อง**”

ถ้าทำดี ๆ `care-agent-platform` จะไม่ใช่แค่ reminder app แต่จะเป็น **personal longitudinal care memory** ที่ช่วยผู้ป่วย ครอบครัว และทีมแพทย์เชื่อมข้อมูลกันอย่างมี governance ได้ครับ


---

## USER

บางวันตื่นมา แม้เป็นวันนัดหมอ แต่ก็ไม่แต่งตัว บางวันนัดตรวจเลือด ได้เอกสารเตรียมร่างกาน แต่ก็ลืม เตรียมร่างกายให้พร้อมสำหรับการนัด


---

## ASSISTANT

ใช่เลยจร้า ตรงนี้ทำให้เห็นว่า **Care Agent ต้องดูแล “กระบวนการไปพบหมอ” ไม่ใช่แค่จำวันนัด** เพราะผู้ป่วยอาจจำไม่ได้ว่ามีนัด หรือจำได้แต่ไม่รู้ว่าต้องเตรียมตัวอะไร

ผมแนะนำเพิ่ม concept สำคัญคือ **Appointment Preparation Agent**

```text
                    Appointment
                         │
                         ▼
                Preparation Plan
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   Before Day        Morning Of       Before Leaving
        │                │                │
   เตรียมเอกสาร       แต่งตัว/อาหาร       ตรวจของ
   เตรียมยา           fasting?            บัตร
   เตรียมเสื้อผ้า      อาบน้ำ              เอกสาร
   เตรียมตัว           เตือนตามเวลา        ยา
        │                │                │
        └────────────────┼────────────────┘
                         ▼
                  Ready to Go?
                         │
                    ┌────┴────┐
                   YES         NO
                    │           │
                 ไปได้      Caregiver
```

### ตัวอย่าง: นัดตรวจเลือด

ระบบไม่ควรแค่บอกว่า

> “พรุ่งนี้ 08:00 นัดตรวจเลือด”

แต่เมื่อ appointment ถูกสร้าง ควรมี **Preparation Plan** จากคำสั่ง/เอกสารของสถานพยาบาลที่ได้รับอนุญาต เช่น

> **พรุ่งนี้ 08:00 ตรวจเลือด**

วันนี้ 18:00:

> “พรุ่งนี้มีนัดตรวจเลือดครับ มีเอกสารเตรียมตัวจากโรงพยาบาลที่ต้องทำตาม ผมจะช่วยเตือนตามขั้นตอนนะครับ”

ก่อนนอน:

> “พรุ่งนี้มีนัดตรวจเลือดนะครับ เตรียมเอกสารไว้แล้วหรือยัง?”

เช้าวันนัด:

> “วันนี้มีนัดตรวจเลือด 08:00 ครับ ตอนนี้ถึงเวลาตื่นและเตรียมตัวแล้ว”

แล้วค่อยถามทีละเรื่อง:

> “แต่งตัวเรียบร้อยแล้วหรือยังครับ?”

> “เตรียมบัตร/เอกสารแล้วหรือยังครับ?”

> “สำหรับการตรวจนี้ มีข้อกำหนดเรื่องอาหารหรือเครื่องดื่มตามเอกสารของโรงพยาบาลนะครับ ผมขอเตือนตามเอกสารที่บันทึกไว้”

**ห้าม Agent เดาเองว่า fasting กี่ชั่วโมง** ถ้าไม่มีคำสั่งที่เชื่อถือได้

---

## และต้องมี “Preparation Checklist” ที่เป็น state

เพราะผู้ป่วยอาจตอบว่า “ครับ” แต่จริง ๆ ยังไม่ได้ทำ

จึงควรมีสถานะ:

```text
PREPARATION
├── appointment_known
├── instructions_received
├── instructions_acknowledged
├── clothes_ready
├── documents_ready
├── medication_ready
├── transport_ready
├── fasting_requirement
├── caregiver_confirmed
└── ready_to_leave
```

แล้ว Agent ตรวจ progress:

```text
Appointment: 08:00

06:00  ตื่นแล้ว          ✓
06:15  แต่งตัว           ✗
06:30  เอกสาร            ✗
06:45  เตรียมตัวตามคำสั่ง ✓
07:00  รถ                ✓
07:15  พร้อมออกจากบ้าน   ✗
```

ถ้าผู้ป่วยไม่ตอบสนองตามเวลาที่กำหนด → **escalation ไป caregiver**

---

# ที่สำคัญ: ต้องรู้ว่า “วันไหนต้องทำอะไร”

ผมจะเพิ่ม **Care Timeline**

```text
         CARE TIMELINE

18 Aug
 │
 ├── 18:00 เตือนนัด
 ├── 20:00 ตรวจ preparation
 │
19 Aug
 │
 ├── 06:00 Wake-up
 ├── 06:15 Preparation
 ├── 06:30 Documents
 ├── 06:45 Medication rules
 ├── 07:00 Transport
 └── 08:00 Blood test
```

นี่ทำให้ Agent เปลี่ยนจาก **calendar reminder** เป็น **workflow engine สำหรับชีวิตจริง**

---

# กรณี “ตื่นมาแล้วไม่ยอมแต่งตัว”

อันนี้น่าสนใจมาก เพราะเป็น **behavior deviation**

```text
Appointment 08:00
       ↓
Expected:
wake → dress → prepare → leave
       ↓
Actual:
wake
 ↓
30 min
 ↓
still not dressed
       ↓
Care Agent
```

Agent ไม่ควรสรุปว่าเป็นอาการ dementia แย่ลง

แต่ควร:

> “วันนี้มีนัดคุณหมอครับ ตอนนี้เรามาเตรียมตัวกันนะครับ เสื้อผ้าที่เตรียมไว้คือชุดนี้”

ถ้ายังไม่ตอบ:

> “ให้ผมแจ้งคุณลูกให้ช่วยเตรียมตัวไหมครับ?”

ถ้ายังไม่มี response:

```text
Routine deviation
       ↓
Caregiver notification
```

---

# และนี่ทำให้ Architecture ของ Care Agent ชัดขึ้นมาก

ผมจะเพิ่ม Agent ตัวใหม่:

```text
                    CARE ORCHESTRATOR
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
 Routine Agent       Health Memory       Appointment
                                               │
                                               ▼
                                  Appointment Preparation
                                               │
                          ┌────────────────────┼─────────────┐
                          ▼                    ▼             ▼
                     Instructions         Checklist       Transport
                          │                    │             │
                          └────────────────────┼─────────────┘
                                               ▼
                                         Caregiver Agent
```

และ **Appointment Preparation Agent ต้องใช้ Workflow + Policy จาก `agent-platform`** ไม่ใช่ให้ LLM คิด flow เอง เพราะ preparation แต่ละชนิดมีข้อกำหนดต่างกัน

---

## ผมว่าตอนนี้ use case หลักของโปรเจกต์กลายเป็น 5 อย่าง

```text
1. REMEMBER
   จำสิ่งที่ผู้ป่วยลืม

2. REMIND
   เตือนสิ่งที่ต้องทำ

3. RECORD
   บันทึกสิ่งผิดปกติ/คำถาม/เหตุการณ์

4. PREPARE
   เตรียมผู้ป่วยก่อนกิจกรรมสำคัญ

5. ESCALATE
   เมื่อผู้ป่วยทำไม่ได้หรือไม่ตอบสนอง
   ให้คนดูแลเข้ามาช่วย
```

และสุดท้าย:

```text
                   PATIENT
                      │
                      ▼
                CARE AGENT
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
    Remember        Prepare        Observe
       │              │              │
       └──────────────┼──────────────┘
                      ▼
                  Assist
                      │
                 Can't handle?
                      │
                      ▼
                 Caregiver
                      │
                 Clinical issue?
                      │
                      ▼
                   Doctor
```

**นี่แหละครับที่ผมคิดว่าเป็น vision ที่แข็งแรงมากของ `care-agent-platform`** — ไม่ใช่ AI ที่บอกว่า “วันนี้มีนัดหมอ” แต่เป็น **AI ที่ช่วยพาคนที่จำอะไรไม่ค่อยได้ ผ่านกิจกรรมสำคัญตั้งแต่ก่อนนัด → เตรียมตัว → เดินทาง → พบหมอ → บันทึกสิ่งที่หมอบอก → ติดตามหลังนัด** โดยยังให้ผู้ดูแลและบุคลากรทางการแพทย์เป็น authority เสมอ.


---

## USER

รายละเอียดของยาแต่ละมื้อ หมอแต่ละคนให้มา เพิ่ม ลด ทุกครั้งที่ไปพบหมอ จำไม่หมดว่า แต่ละมื้อทานอะไร ก่อนอาหาร หลังอาหาร


---

## ASSISTANT

ใช่เลยจร้า ตรงนี้คือ **Medication Management + Medication Reconciliation** ซึ่งควรเป็น core มาก ๆ เพราะปัญหาไม่ได้อยู่แค่ “เตือนกินยา” แต่คือ **จำไม่ได้ว่าใครสั่งอะไร เปลี่ยนเมื่อไร กินมื้อไหน ก่อน/หลังอาหาร และคำสั่งเก่าถูกยกเลิกหรือยัง**

ผมแนะนำให้เพิ่มเป็น **Medication Memory** โดยเฉพาะ

```text id="j4r8s2"
                    MEDICATION MEMORY
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
        Medication History        Current Regimen
              │                         │
       ใครสั่ง / เมื่อไร             กินอะไร
       เพิ่ม / ลด / หยุด             กี่เม็ด
       เปลี่ยนขนาด                  เวลาไหน
       เหตุผล/หมายเหตุ              ก่อน/หลังอาหาร
              │                         │
              └────────────┬────────────┘
                           ▼
                    Daily Medication Plan
```

### ตัวอย่างที่ผู้ป่วยเห็น

ไม่ต้องให้ผู้ป่วยจำชื่อยาเยอะ ๆ

**เช้า**

```text
07:00
💊 ยา A — 1 เม็ด
🍚 ก่อนอาหาร

08:00
💊 ยา B — 1 เม็ด
🍚 หลังอาหาร
```

**กลางวัน**

```text
12:00
💊 ยา C — 1 เม็ด
🍚 หลังอาหาร
```

**เย็น**

```text
18:00
💊 ยา A — 1 เม็ด
🍚 ก่อนอาหาร
```

**ก่อนนอน**

```text
21:00
💊 ยา D — 1 เม็ด
🌙 ก่อนนอน
```

แต่ข้างหลังต้องมีข้อมูลละเอียดกว่านั้น

---

# สิ่งสำคัญมาก: Medication Versioning

สมมติ:

```text
1 Aug
หมอ A
ยา X 1 เม็ด เช้า

10 Aug
หมอ B
ยา X ลดเหลือ 1/2 เม็ด

18 Aug
หมอ A
ยา X หยุด
```

ห้ามระบบเก็บแค่:

```text
ยา X = หยุด
```

ต้องเก็บ history:

```text id="r6d3kq"
Medication X

v1
01 Aug
Doctor A
1 tablet morning
ACTIVE

v2
10 Aug
Doctor B
0.5 tablet morning
SUPERSEDED

v3
18 Aug
Doctor A
STOP
ACTIVE
```

ดังนั้นถ้าถาม:

> “เมื่อก่อนกินยาตัวนี้ยังไง?”

Agent ตอบจาก history ได้

แต่ถ้าถาม:

> “ตอนนี้ต้องกินยังไง?”

ต้องตอบจาก **current active medication regimen เท่านั้น**

---

# ต้องรู้ด้วยว่า “หมอคนไหนสั่ง”

```text id="v9x3kt"
Medication
    │
    ├── prescribed_by
    │       └── Neurologist
    │
    ├── prescribed_at
    │
    ├── changed_by
    │       └── Cardiologist
    │
    └── status
```

เพราะผู้ป่วยอาจมีหมอหลายคน และเกิดปัญหา:

> หมอคนหนึ่งเพิ่มยา

> อีกคนลด/หยุดยา

Agent ต้อง **ไม่ตัดสินเองว่าใครถูก**

แต่ต้อง detect conflict:

```text id="3j2p7c"
Medication Conflict
       │
       ├── Doctor A: 1 tablet
       └── Doctor B: 0.5 tablet
                    ↓
             NEED RECONCILIATION
                    ↓
              Caregiver / Doctor
```

นี่สำคัญมากสำหรับ safety

---

# “ก่อนอาหาร / หลังอาหาร” ต้องเป็น structured data

อย่าเก็บเป็นข้อความอย่างเดียว

```yaml id="j8m1as"
medication:
  name: "Medication A"
  dose: "1 tablet"
  route: "oral"

  schedule:
    - time: "07:00"
      relation_to_meal: "before_meal"

    - time: "18:00"
      relation_to_meal: "after_meal"
```

รองรับอย่างน้อย:

```text
before_meal
with_meal
after_meal
empty_stomach
bedtime
morning
as_needed
specific_time
```

และควรมี `instruction_source` เช่น

```text
doctor_instruction
pharmacy_label
hospital_document
caregiver_entry
patient_entry
```

เพื่อรู้ว่า information มาจากไหน

---

# ที่เจ๋งคือเอาไปผูกกับ Meal Agent ได้

แทนที่จะเตือนแบบ:

> “ถึงเวลากินยา”

Agent รู้ context:

```text id="n8nq42"
Breakfast
   │
   ├── Medication A
   │     └── BEFORE MEAL
   │
   └── Medication B
         └── AFTER MEAL
```

จึงกลายเป็น:

> “ก่อนทานอาหารเช้า มี 1 รายการที่ต้องทานก่อนอาหารครับ”

หลังผู้ป่วยกินข้าว:

> “ตอนนี้หลังอาหารเช้า มียาอีก 1 รายการครับ”

**ตรงนี้จะช่วยลด cognitive load ได้เยอะมาก**

---

# และควรมี “Medication Reconciliation ก่อนพบหมอ”

ก่อนพบหมอ:

```text id="3jv6qg"
Upcoming Doctor
      │
      ▼
Current Medication
      +
Recent Changes
      +
Missed Doses
      +
Side Effects / Symptoms
      │
      ▼
Medication Summary
```

เช่น:

> **สรุปยาเพื่อพบคุณหมอ**
>
> ยาปัจจุบัน 6 รายการ  
> เพิ่มใหม่ 1 รายการ  
> ลดขนาด 2 รายการ  
> หยุด 1 รายการ  
> ลืมทาน 2 ครั้งในสัปดาห์นี้  
> มีอาการง่วงหลังทานยา 3 ครั้ง

ทำให้ผู้ป่วยไม่ต้องจำเอง

---

# และหลังพบหมอ

นี่ควรเป็น workflow ใหญ่:

```text id="y4l7s9"
Doctor Visit
     │
     ▼
Doctor changes medication
     │
     ▼
Capture instruction
     │
     ▼
Human confirmation
     │
     ▼
Create new medication version
     │
     ▼
Supersede old regimen
     │
     ▼
Update daily schedule
     │
     ▼
Notify caregiver
     │
     ▼
Audit
```

**ไม่ควรให้ LLM ฟังคำพูดหมอแล้วแก้ medication database เองโดยไม่มี confirmation** โดยเฉพาะ dose/frequency/stop-start

---

# ดังนั้น Care Agent ตอนนี้จะมี “Memory” ที่สำคัญมาก

```text id="j3s5qk"
                    PATIENT MEMORY
                          │
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
 Daily Routine       Health Journal      Medication
       │                  │                  │
       │                  │            version/history
       │                  │            doctor/source
       │                  │            dose/schedule
       │                  │            meal relation
       │                  │
       └──────────────────┼──────────────────┘
                          ▼
                    Appointments
                          │
                          ▼
                 Doctor Visit Memory
                          │
                          ▼
                   Care Timeline
```

ผมจะปรับ vision ของระบบเป็น:

> **“External Memory & Care Orchestrator สำหรับผู้ป่วย”**

มันช่วยจำแทนผู้ป่วยตั้งแต่

**“หมอสั่งอะไร” → “ต้องเตรียมตัวอย่างไร” → “วันนี้ต้องกินอะไร” → “ก่อนหรือหลังอาหาร” → “กินแล้วหรือยัง” → “เกิดอะไรขึ้นระหว่างทาง” → “ครั้งหน้าต้องบอกหมออะไร”**

และทั้งหมดต้องมี **source + timestamp + version + audit + human confirmation** เพื่อไม่ให้ความจำของ AI กลายเป็นคำสั่งทางการแพทย์โดยไม่ได้ตั้งใจ

อันนี้ผมว่าเป็น feature ที่ควรยกระดับเป็น **MVP Core** ของ `care-agent-platform` เลยครับ


---

## USER

คำแนะนำหลังพบหมอ เช่น ให้ใช้ยานวด ให้เดินออกกำลัง ให้กินน้ำเพิ่ม ก็ลืม บางครั้งตื่นมาก็ลืมวันลืมคืน


---

## ASSISTANT

ใช่เลยจร้า และตรงนี้ทำให้ภาพของระบบชัดขึ้นอีกขั้น — **ไม่ใช่แค่ Medication Reminder แต่ต้องเป็น “Care Plan Memory + Orientation Assistant”** เพราะคำแนะนำหลังพบหมอก็เป็นสิ่งที่ผู้ป่วยต้อง “ทำต่อเนื่อง” และอาจลืมวัน/เวลาได้

## 1. หลังพบหมอ → แปลงคำแนะนำเป็น Care Plan

ตัวอย่างหมอบอกว่า:

> ใช้ยานวดวันละ 2 ครั้ง  
> เดินออกกำลังกายวันละ 20 นาที  
> ดื่มน้ำเพิ่ม  
> กลับมาตรวจอีก 1 เดือน

Agent ไม่ควรเก็บเป็นข้อความยาว ๆ อย่างเดียว แต่แปลงเป็น structured care tasks:

```text id="k8kz5n"
Doctor Visit
      │
      ▼
Care Instructions
      │
 ┌────┼────────┬─────────┐
 ▼    ▼        ▼         ▼
ยา   Exercise  Hydration  Follow-up
 │      │         │          │
2x/day 20 min    daily      1 month
```

แล้วนำเข้า **Care Timeline**

---

## 2. วันรุ่งขึ้นผู้ป่วยไม่ต้องจำเอง

ตอนเช้า Agent สามารถพูด:

> “สวัสดีครับ วันนี้วันอังคารที่ 19 สิงหาคม วันนี้มี 3 อย่างที่คุณหมอฝากให้ทำครับ”

> “หนึ่ง ใช้ยานวดตอนเช้า”

> “สอง เดินออกกำลังกายประมาณ 20 นาที”

> “สาม วันนี้พยายามดื่มน้ำตามแผนที่คุณหมอแนะนำครับ”

ไม่ต้องเปิดแอป ไม่ต้องจำคำสั่งจากหมอ

---

# 3. “ตื่นมาไม่รู้วันไหน” ต้องมี Orientation Agent

อันนี้ผมว่า **ควรเป็น core feature** สำหรับกลุ่มที่มีปัญหาความจำ

เมื่อผู้ป่วยตื่น:

```text id="vwx0gk"
                    MORNING ORIENTATION
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
           Date           Time         Context
             │             │             │
        วันนี้วันอะไร    ตอนนี้กี่โมง    วันนี้ต้องทำอะไร
             │             │             │
             └─────────────┼─────────────┘
                           ▼
                      Daily Brief
```

เช่น:

> **สวัสดีตอนเช้าครับ**
>
> วันนี้วันอังคารที่ 19 สิงหาคม  
> เวลา 07:10 น.
>
> วันนี้ไม่มีนัดหมอครับ  
> ตอนเช้ามียา 2 รายการ  
> และคุณหมอแนะนำให้เดิน 20 นาที
>
> ตอนนี้ถึงเวลาทานอาหารเช้าแล้วครับ

ถ้าถามซ้ำ:

> “วันนี้วันอะไรนะ?”

ตอบเหมือนเดิมได้ **โดยไม่ทำให้ผู้ป่วยรู้สึกผิด**

> “วันนี้วันอังคารที่ 19 สิงหาคมครับ 😊”

---

# 4. Orientation ไม่ควรเป็นแค่ Date/Time

ผมจะทำเป็น **5-layer orientation**

```text id="w1kz5e"
1. TIME
   ตอนนี้กี่โมง

2. DATE
   วันนี้วันอะไร

3. PLACE
   ตอนนี้อยู่ที่ไหน

4. PERSON
   วันนี้จะพบใคร

5. PLAN
   วันนี้ต้องทำอะไร
```

ตัวอย่าง:

> “ตอนนี้อยู่ที่บ้านครับ วันนี้วันอังคารที่ 19 สิงหาคม เวลา 07:15 น. วันนี้ไม่มีนัดหมอ แต่มีนัดคุณลูกมาหาตอน 10 โมงครับ”

---

# 5. แล้วเชื่อมกับ Care Plan

สิ่งที่หมอสั่งหลังพบหมอจะไม่หายไปใน medical note

มันกลายเป็น:

```text id="bdqk2v"
DOCTOR
  │
  ▼
CARE PLAN
  │
  ├── Medication
  ├── Exercise
  ├── Nutrition
  ├── Hydration
  ├── Wound / Massage
  ├── Sleep
  ├── Follow-up
  └── Restrictions
       │
       ▼
DAILY ROUTINE
       │
       ▼
REMINDER
       │
       ▼
CONFIRMATION
       │
       ▼
ADHERENCE
```

ดังนั้นถ้าหมอบอก

> “เดินทุกวัน”

ระบบจะไม่จบที่ note

แต่สร้าง:

```yaml id="2ax9fc"
care_task:
  type: exercise
  activity: walking
  duration: 20m
  frequency: daily
  source: doctor_visit
  start_date: ...
  end_date: ...
```

---

# 6. ต้องรองรับ “คำสั่งที่ไม่มีวันสิ้นสุด”

เช่น

> “ดื่มน้ำให้มากขึ้น”

ไม่ใช่ appointment

เป็น **long-running care plan**

```text id="7wmxhe"
Doctor Instruction
       │
       ▼
Long-running Care Plan
       │
       ├── Daily reminder
       ├── Progress
       ├── Adherence
       └── Review at next visit
```

ครั้งหน้าหมอถาม:

> “ช่วงนี้ได้เดินออกกำลังกายไหม?”

Agent มีข้อมูล:

> “ในช่วง 30 วันที่ผ่านมา ทำได้ 22 วันครับ”

แต่ต้องระวังไม่สร้างข้อมูลที่ไม่มีหลักฐาน — ถ้าไม่ได้บันทึก ก็ต้องบอกว่า **ไม่มีข้อมูลเพียงพอ**

---

# 7. Care Agent ต้องรู้ “วันไหน”

ตรงนี้ผมจะเพิ่ม **Temporal Memory**

```text id="h1a3xn"
Past
 │
 ├── เมื่อวาน
 ├── สัปดาห์ก่อน
 └── นัดครั้งก่อน

Today
 │
 ├── ตอนเช้า
 ├── ตอนนี้
 └── วันนี้

Future
 │
 ├── พรุ่งนี้
 ├── วันนัดหมอ
 └── Follow-up
```

ผู้ป่วยพูด:

> “พรุ่งนี้ต้องทำอะไรนะ?”

Agent สามารถ resolve `พรุ่งนี้` จาก actual date แล้วค้น timeline

ไม่ใช่ให้ LLM เดา

---

# 8. และมี “Daily Brief” อัตโนมัติ

ผมว่าเป็นหนึ่งในหน้าหลักของระบบเลย

```text id="u5i8g4"
┌─────────────────────────────┐
│       วันนี้ของคุณ          │
├─────────────────────────────┤
│ อังคาร 19 สิงหาคม           │
│ เวลา 07:15                   │
│                             │
│ ☀️ ตอนเช้า                  │
│ 🍚 อาหารเช้า                │
│ 💊 ยา 2 รายการ              │
│                             │
│ 👨‍⚕️ วันนี้ไม่มีนัดหมอ       │
│                             │
│ 🚶 เดิน 20 นาที              │
│ 💧 ทำตามแผนการดื่มน้ำ        │
│                             │
│ 👨‍👩‍👧 ลูกมาหา 10:00          │
└─────────────────────────────┘
```

แล้วผู้ป่วยไม่ต้องคิดเองว่า

> “วันนี้ต้องทำอะไรบ้าง?”

---

# 9. ถ้าผู้ป่วยไม่ทำ

อย่า spam notification

ใช้ escalation policy:

```text id="3xw1cn"
Reminder
   ↓
Wait
   ↓
Gentle reminder
   ↓
Wait
   ↓
Ask patient
   ↓
Still unresolved?
   ↓
Caregiver
```

และปรับตามแต่ละคนได้

---

# 10. Architecture ตอนนี้ผมจะเพิ่ม 3 Agent

จากที่คุยกันมา:

```text id="kh0kzs"
                    CARE ORCHESTRATOR
                           │
       ┌───────────────────┼────────────────────┐
       ▼                   ▼                    ▼
 Orientation          Care Plan           Appointment
   Agent                Agent              Preparation
       │                   │                    │
       │              ┌────┼────┐               │
       │              ▼    ▼    ▼               │
       │             Med Exercise Nutrition      │
       │                   │                    │
       └───────────────────┼────────────────────┘
                           ▼
                    Daily Care Plan
                           │
                           ▼
                    Caregiver Agent
```

### Orientation Agent

**“วันนี้คือวันอะไร / อยู่ที่ไหน / ต้องทำอะไร”**

### Care Plan Agent

**“หมอสั่งอะไรไว้ ต้องทำเมื่อไร ทำไปแล้วหรือยัง”**

### Appointment Preparation Agent

**“นัดครั้งนี้ต้องเตรียมอะไรบ้าง”**

สามตัวนี้รวมกันจะทำให้ระบบแตกต่างจาก reminder app ทั่วไปมาก

---

# Vision ที่ผมว่าใช่แล้ว

จากทุกตัวอย่างที่เล่ามา ผมจะนิยามโปรเจกต์นี้ว่า:

> **AI External Memory & Care Companion**

หรือภาษาไทย:

> **“ผู้ช่วยความจำและการดูแลส่วนตัวสำหรับผู้ป่วย”**

มันทำหน้าที่เป็น **สมองภายนอก** ในเรื่องที่ผู้ป่วยมีโอกาสลืม:

```text id="2x4nqk"
                 ┌────────────────────┐
                 │    PATIENT LIFE    │
                 └─────────┬──────────┘
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          REMEMBER       PREPARE       OBSERVE
             │             │             │
          จำแทน         เตรียมแทน       สังเกต
             │             │             │
             └─────────────┼─────────────┘
                           ▼
                         GUIDE
                           │
                           ▼
                        VERIFY
                           │
                     ┌─────┴─────┐
                     ▼           ▼
                  SUCCESS     PROBLEM
                                 │
                                 ▼
                            CAREGIVER
                                 │
                                 ▼
                              DOCTOR
```

และ **“ตื่นมาไม่รู้วันไหน” ไม่ควรถูกมองเป็น edge case** แต่ควรเป็นหนึ่งใน scenario หลักที่ทีมต้องเอาไปทำ automated test ตั้งแต่ MVP เลยครับ

เช่น test scenario:

> `Patient wakes up → asks date → receives orientation → gets today's care plan → medication reminder → appointment preparation → caregiver escalation if patient does not respond.`

นี่จะทำให้ทีมสร้างระบบที่แก้ **ชีวิตจริงของผู้ป่วย** ไม่ใช่แค่สร้าง chatbot ที่ตอบคำถามได้ครับ


---

## USER

เรื่องเสื้อผ้า ใช้แล้ว ยังไม่ได้ใช้ ก็ลืม จับรวมกัน แยกไม่ออกเลย อันไหนเก่าใหม่


---

## ASSISTANT

ใช่ครับ และนี่เป็นตัวอย่างที่ดีมากว่า **Care Agent ต้องช่วยเรื่อง “การจัดการสิ่งแวดล้อมและของใช้ประจำวัน” ด้วย** ไม่ใช่เฉพาะยา/หมอ

แต่ผมจะออกแบบอย่างระมัดระวัง: **AI ไม่ควรพยายามเดาจากภาพว่าเสื้อผ้าตัวไหน “สะอาด/สกปรก” แล้วสั่งผู้ป่วยทันที** เพราะความผิดพลาดทำให้เกิดปัญหาได้ ควรใช้ระบบที่ผู้ดูแลกำหนด workflow ง่าย ๆ และมีการยืนยัน

## เพิ่มเป็น “Daily Living Assistant”

```text id="k6r8qx"
                 CARE AGENT
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
   Health Care   Daily Living   Orientation
       │             │             │
       │             ├── Clothes
       │             ├── Meals
       │             ├── Hygiene
       │             ├── Personal items
       │             └── Household routine
       │
       ▼
   Caregiver
```

### เสื้อผ้า

แทนที่จะให้ผู้ป่วยจำว่าอะไรใช้แล้ว ให้สร้าง **สถานะที่มองเห็นง่าย**

```text id="q6k4yd"
👕 เสื้อผ้า

🟢 สะอาด / พร้อมใส่
🟡 ใช้แล้ว / รอซัก
🔵 กำลังซัก
⚪ ยังไม่ได้ใช้
```

หรือให้เข้าใจง่ายกว่านั้นคือ **แยกพื้นที่จริง**

```text id="s7y0kr"
┌─────────────────┐
│ 👕 พร้อมใส่     │
│                 │
└─────────────────┘

┌─────────────────┐
│ 🧺 ใช้แล้ว      │
│ ใส่ตะกร้านี้    │
└─────────────────┘
```

**ลดการพึ่งพาความจำของผู้ป่วยให้มากที่สุด**

---

## Agent ไม่ควรถามว่า “ตัวนี้สะอาดไหม?”

ให้ workflow ง่าย ๆ:

> “ชุดนี้ใส่แล้วหรือยังครับ?”

ถ้าผู้ป่วยตอบ:

> “จำไม่ได้”

Agent:

> “ไม่เป็นไรครับ ใส่ไว้ในตะกร้าผ้าที่ใช้แล้วก่อนนะครับ”

หลักคือ **เมื่อไม่แน่ใจ → เลือก safe/default workflow** แทนการให้ AI เดา

---

# ยิ่งไปกว่านั้น ทำ “Daily Setup”

ตอนกลางคืน Agent สามารถช่วยเตรียมวันพรุ่งนี้:

> “พรุ่งนี้มีนัดคุณหมอ 9 โมงครับ”

> “ผมแนะนำให้เตรียมเสื้อผ้าสำหรับพรุ่งนี้ไว้ตรงนี้นะครับ”

ถ้ามี caregiver:

> “พรุ่งนี้มีนัดหมอ 09:00 ช่วยเตรียมชุดและเอกสารไว้ให้ด้วยครับ”

เช้าวันรุ่งขึ้น:

> “วันนี้มีนัดหมอครับ ชุดที่เตรียมไว้สำหรับวันนี้อยู่ตรงนี้ครับ”

---

# นี่ทำให้เกิด Concept ใหญ่ขึ้น

จากที่เล่ามาทั้งหมด ผมจะเพิ่ม **Daily Living Agent**

มันดูแลเรื่องที่คนทั่วไปมองว่าเล็ก แต่สำหรับคนที่ความจำเริ่มมีปัญหา มันกระทบชีวิตประจำวันมาก:

```text id="9h9k4d"
Daily Living Agent
│
├── Clothing
│   ├── clean
│   ├── used
│   └── laundry
│
├── Meals
│   ├── breakfast
│   ├── lunch
│   └── dinner
│
├── Hygiene
│   ├── shower
│   ├── brushing
│   └── changing clothes
│
├── Personal Items
│   ├── keys
│   ├── wallet
│   ├── glasses
│   └── phone
│
└── Daily Routine
```

แล้วเชื่อมกับ Orientation:

```text id="q0s4cj"
ตื่นนอน
  ↓
วันนี้วันอะไร?
  ↓
วันนี้มีนัดไหม?
  ↓
ต้องแต่งตัวแบบไหน?
  ↓
เสื้อผ้าที่เตรียมไว้
  ↓
ทานอาหาร
  ↓
ยา
  ↓
ออกจากบ้าน
```

---

## หลักการออกแบบที่ผมอยากให้ทีมจำไว้

**อย่าพยายามทำให้ AI “จำแทนทุกอย่าง” อย่างเดียว**

ให้ AI ช่วย **ออกแบบ environment ให้ไม่ต้องจำ**

ตัวอย่าง:

```text id="9t5x2k"
ปัญหา:
จำไม่ได้ว่าเสื้อผ้าตัวไหนใช้แล้ว

วิธีที่ไม่ดี:
AI วิเคราะห์ภาพแล้วบอกว่านี่สะอาด

วิธีที่ดีกว่า:
กำหนด physical workflow
        ↓
ใช้แล้ว → ตะกร้า
ยังไม่ใช้ → ตู้
        ↓
Agent เตือน workflow
        ↓
Caregiver ช่วยเมื่อผิดปกติ
```

นี่คือแนวคิด **Cognitive Offloading** — เอางานที่ต้องใช้ความจำออกจากสมองของผู้ป่วย แล้วไปไว้ใน environment + software + caregiver

และผมว่าควรเป็นหนึ่งในหลักการออกแบบหลักของ `care-agent-platform` เลย:

> **“Don't just remind the patient. Reduce the amount of things the patient has to remember.”**

จากตัวอย่างทั้งหมดที่เล่ามา นี่กำลังกลายเป็นระบบ **“External Memory + Daily Living + Care Coordination”** มากกว่า healthcare chatbot ธรรมดาแล้วครับ


---

## USER

บางทีขยัน อยากซักผ้า ก็เอาผ้าเข้าเครื่อง ไม่ได้ดูบรรยากาศเลย ฝนจะตกก็ยังจะซัก เอาใส่เครื่อง แล้วก็ลืม เลือกโปรแกรม ลืม กด start เริ่มทำงาน บางทีเรียบร้อยเครื่องทำงานจบ แต่ก็ลืมเอาไปตาก


---

## ASSISTANT

ใช่ครับ นี่เป็น use case ที่สำคัญมาก เพราะมันไม่ใช่แค่ “ลืมซักผ้า” แต่เป็น **งานหลายขั้นตอนที่เริ่มได้ แต่ทำไม่จบ (multi-step task failure)** ซึ่งเป็นสิ่งที่ Care Agent ควรเข้ามาช่วยโดยตรง

ผมจะเพิ่ม concept ใหญ่ชื่อ **Task Companion / Activity Agent** เข้าไปใน platform

```text
                  ACTIVITY AGENT
                       │
              ┌────────┴────────┐
              ▼                 ▼
        Task Planning       Task Monitoring
              │                 │
              ▼                 ▼
        Step-by-step       Detect stuck
              │                 │
              └────────┬────────┘
                       ▼
                  Completion
```

## ตัวอย่าง “ซักผ้า”

แทนที่จะบอกแค่:

> “วันนี้ซักผ้านะ”

Agent ต้องรู้ว่า **งานซักผ้ามีหลายขั้น**

```text id="b3c8h2"
ซักผ้า
 │
 ├─ 1. ตรวจอากาศ
 │
 ├─ 2. เตรียมผ้า
 │
 ├─ 3. ใส่เครื่อง
 │
 ├─ 4. ใส่น้ำยา
 │
 ├─ 5. เลือกโปรแกรม
 │
 ├─ 6. กด Start
 │
 ├─ 7. รอเครื่องทำงาน
 │
 ├─ 8. เครื่องเสร็จ
 │
 └─ 9. เอาผ้าไปตาก
```

แต่ละขั้นมี state:

```yaml id="7u6qzw"
task:
  type: laundry
  status: in_progress

steps:
  - prepare
  - load
  - detergent
  - program
  - start
  - running
  - completed
  - hang_clothes
```

---

# จุดที่น่าสนใจมากคือ “บริบท”

ถ้าผู้ป่วยพูด:

> “วันนี้จะซักผ้า”

Agent ไม่ควรตอบทันทีว่า:

> “ได้เลยครับ”

แต่ตรวจ context ก่อน

```text id="4zq7zj"
Laundry request
      │
      ├── Weather
      ├── Time
      ├── Current tasks
      ├── Machine status
      └── Care plan
             │
             ▼
         Decision
```

เช่นถ้าพยากรณ์อากาศบอกว่าฝนกำลังจะตก:

> “วันนี้มีโอกาสฝนตกช่วงบ่ายครับ ถ้าต้องการตากผ้า อาจซักช่วงเช้าและตากให้เสร็จก่อนฝนครับ”

**ไม่ใช่ห้ามซักเอง** เพราะ AI ไม่ควรควบคุมชีวิตผู้ป่วยโดยไม่มีเหตุผล/authority

---

# แล้วระหว่างซัก Agent ต้อง “อยู่กับงาน”

นี่คือความแตกต่างจาก reminder app

```text id="h0yq2e"
User:
"จะซักผ้า"

Agent:
"ได้ครับ เดี๋ยวผมช่วยทีละขั้น"

        ↓

"ใส่ผ้าในเครื่องแล้วหรือยังครับ?"

        ↓

"ใส่น้ำยาแล้วหรือยังครับ?"

        ↓

"เลือกโปรแกรมเรียบร้อยแล้วหรือยังครับ?"

        ↓

"กด Start แล้วหรือยังครับ?"
```

ถ้าเครื่องมี IoT integration:

```text id="6z4k7u"
Machine
   │
   ├── door_closed
   ├── program_selected
   ├── running
   ├── remaining_time
   └── finished
```

Agent ไม่ต้องถามทุกอย่าง

มันรู้จากเครื่อง:

> “เครื่องกำลังซักอยู่ครับ เหลือประมาณ 35 นาที”

---

# จุดที่สำคัญที่สุด: “เครื่องเสร็จแล้ว แต่ผ้าค้าง”

นี่เป็น **completion failure**

```text id="r7j2w1"
Machine finished
       │
       ▼
Laundry task ≠ completed
       │
       ▼
Need next step:
Hang clothes
```

หลังเครื่องเสร็จ:

> “เครื่องซักผ้าทำงานเสร็จแล้วครับ ตอนนี้นำผ้าออกไปตากได้แล้วครับ”

ถ้า 30 นาทีผ่านไป:

> “ผ้ายังอยู่ในเครื่องซักผ้าครับ ต้องการให้ผมเตือนอีกครั้งไหมครับ?”

ถ้ายังไม่มี response:

```text id="l1p8y0"
Laundry finished
      ↓
Reminder
      ↓
No response
      ↓
Caregiver notification
```

---

# นี่เรียกว่า Task Continuity

ผมคิดว่าควรเป็น primitive ของ `agent-platform` ด้วยซ้ำ

เพราะหลายงานของมนุษย์เป็นแบบ:

```text
START → STEPS → WAIT → EVENT → NEXT STEP → COMPLETE
```

เช่น:

```text
ซักผ้า
ทำอาหาร
เตรียมตัวไปหาหมอ
กินยา
อาบน้ำ
ออกกำลังกาย
ทำความสะอาด
```

Agent ต้องไม่คิดว่า:

> “ผมส่ง reminder แล้ว = งานเสร็จ”

แต่ต้องคิดว่า:

> **“งานอยู่ขั้นตอนไหน?”**

---

# ผมจะแยก Task State ออกมา

```text id="h5n3pd"
TASK
│
├── NOT_STARTED
├── STARTING
├── IN_PROGRESS
├── WAITING
├── BLOCKED
├── READY_FOR_NEXT_STEP
├── COMPLETED
├── ABANDONED
└── NEEDS_HELP
```

เช่น:

```text id="e8h2qz"
Laundry

08:00 NOT_STARTED
08:05 STARTING
08:10 IN_PROGRESS
08:11 RUNNING
09:00 READY_FOR_NEXT_STEP
09:30 NEEDS_HELP
```

---

# และจะช่วยเรื่อง “ขยันแต่ทำงานไม่จบ”

นี่เป็น pattern ที่ควร monitor:

```text id="w5q9lm"
Patient starts many tasks
       │
       ├── laundry → unfinished
       ├── cooking → unfinished
       ├── cleaning → unfinished
       └── appointment prep → unfinished
```

Agent ไม่ควรตีความว่า:

> “ผู้ป่วยแย่ลง”

แต่สามารถแจ้ง caregiver:

> “วันนี้มีงานที่เริ่มแล้วแต่ยังไม่เสร็จ 3 รายการ”

นี่เป็น **objective observation** และ caregiver เป็นคนประเมินต่อ

---

# Architecture ตอนนี้เริ่มเป็นรูปใหญ่แล้ว

```text id="v3q8kp"
                    CARE AGENT
                         │
              CARE ORCHESTRATOR
                         │
 ┌───────────┬───────────┼───────────┬───────────┐
 ▼           ▼           ▼           ▼           ▼
Memory     Health      Routine     Activity    Safety
Agent      Agent       Agent       Agent       Agent
 │           │           │           │           │
 │           │           │           │           │
 ▼           ▼           ▼           ▼           ▼
Journal     Medicine    Daily       Tasks       IoT
Questions   Appointment  Living      Workflow    Sensors
```

และด้านล่าง:

```text id="1kq9wc"
               EVENT / WORKFLOW ENGINE
                         │
                    POLICY ENGINE
                         │
                  ESCALATION ENGINE
                         │
                  CAREGIVER / FAMILY
```

---

## และมีหลักการหนึ่งที่ผมอยากเพิ่มใน blueprint

### **Agent ต้องช่วย “ทำให้จบ” ไม่ใช่แค่ “เตือนให้เริ่ม”**

นี่จะกลายเป็นหัวใจของระบบเลย

```text id="h6x3fz"
Traditional Reminder

เตือน → ผู้ใช้ทำเอง → จบ
```

แต่:

```text id="v2m7qs"
Care Agent

เข้าใจเป้าหมาย
      ↓
เตรียมบริบท
      ↓
เริ่มงาน
      ↓
ติดตามแต่ละขั้น
      ↓
ตรวจว่าขั้นนั้นเสร็จจริง
      ↓
รอ event
      ↓
ทำขั้นถัดไป
      ↓
ตรวจ completion
      ↓
ถ้าติดขัด → ช่วย
      ↓
ถ้าช่วยไม่ได้ → caregiver
```

ดังนั้น **ซักผ้า** อาจดูเป็นเรื่องเล็ก แต่จริง ๆ แล้วเป็น PoC ที่ดีมากสำหรับ platform เพราะมัน test ได้ครบทั้ง **context awareness + multi-step workflow + state tracking + IoT + weather + memory + task continuity + escalation** ใน scenario เดียว

และต่อไปก็สามารถเอา engine เดียวกันไปใช้กับ **“เตรียมตัวไปหาหมอ → เตรียมเอกสาร → แต่งตัว → กิน/งดยาตามคำสั่ง → ออกจากบ้าน → ไปถึงโรงพยาบาล”** ได้เลยครับ.


---

## USER

อาหาร ซื้อมาก็ลืมทาน แล้วก็ไปซื้อมาใหม่


---

## ASSISTANT

ใช่ครับ อันนี้ยิ่งตอกย้ำว่า **ระบบต้องดูแล “สิ่งของ + งาน + เวลา + ความจำ” ไปพร้อมกัน** ไม่ใช่แค่ health reminder

กรณีอาหาร:

> ซื้ออาหารมา → เก็บไว้ → ลืมว่ามี → ซื้อเพิ่ม → ของเก่าหมดอายุ

นี่คือ **Inventory Memory + Meal Agent** และควรเอาเข้าระบบตั้งแต่ค่อนข้างเร็ว

### ตัวอย่างที่ผู้ป่วยเห็น

```text id="bq8m2p"
        🏠 ของที่มีอยู่

🍚 ข้าว
   มีอยู่

🥛 นม
   2 กล่อง
   ควรใช้ก่อน: พรุ่งนี้

🍌 กล้วย
   4 ลูก
   ควรทานก่อน: 20 ส.ค.

🍲 อาหารสำเร็จรูป
   2 ชุด
   ควรทานก่อน: 21 ส.ค.
```

ตอนผู้ป่วยพูดว่า:

> “จะออกไปซื้ออาหาร”

Agent สามารถถามง่าย ๆ:

> “ที่บ้านยังมีอาหารสำหรับวันนี้อยู่ครับ ต้องการให้ผมดูก่อนว่าอะไรควรทานก่อนหรือไม่?”

ไม่จำเป็นต้องห้ามซื้อ

---

## หลักสำคัญคือ “Use What You Have”

สร้าง **Food Inventory**

```text id="m3h7vs"
Food
 │
 ├── item
 ├── quantity
 ├── purchase_date
 ├── expiry / best_before
 ├── storage_location
 └── status
```

แล้วเชื่อมกับ Meal Plan:

```text id="8kq2zd"
Food Inventory
       │
       ▼
Meal Planner
       │
       ▼
Today's Meals
       │
       ▼
Food consumed?
       │
   ┌───┴───┐
  YES      NO
   │        │
 update    reminder
 inventory
```

---

# และ “ลืมว่ากินแล้วหรือยัง” ก็เป็นอีกเรื่อง

เช่นตอน 12:30:

> “ทานข้าวกลางวันแล้วหรือยังครับ?”

ผู้ป่วย:

> “จำไม่ได้”

**อย่าให้ Agent เดา**

ตรวจจาก evidence ที่มี:

```text id="j4q1cx"
Meal event
 ├── Patient confirmed
 ├── Caregiver confirmed
 ├── Smart kitchen
 └── No evidence
```

ถ้าไม่มีหลักฐาน:

> “ยังไม่มีข้อมูลว่าทานแล้วครับ ถ้าจำไม่ได้ ลองเช็กอาหารที่เตรียมไว้ก่อนนะครับ”

และถ้าความปลอดภัยเกี่ยวข้อง ให้ caregiver ช่วยตรวจ

---

# ซื้อซ้ำก็เป็น Event ที่มีประโยชน์

ถ้าระบบเชื่อม receipt / shopping list / caregiver entry ได้:

```text id="z3g6av"
ซื้อ:
นม 2 กล่อง

Inventory:
นม 4 กล่อง

User:
"จะซื้อนมอีก"
       ↓
Agent:
"ตอนนี้ที่บ้านมีนมอยู่ 4 กล่องครับ
ต้องการซื้อเพิ่มจริง ๆ หรือไม่?"
```

นี่เป็น **memory augmentation** ไม่ใช่การควบคุมผู้ป่วย

---

# ที่น่าสนใจคือมันเชื่อมกับ “โภชนาการ”

ไม่ใช่แค่ป้องกันซื้อซ้ำ

Agent สามารถรู้:

```text id="9j3zv2"
Today's Plan

Breakfast ✓
Lunch ?
Dinner ?

Food available:
rice
egg
milk
fruit
```

แล้วช่วยเสนอ:

> “วันนี้ยังไม่ได้ทานมื้อกลางวันครับ ที่บ้านมีอาหารที่เตรียมไว้ สามารถทานได้เลยครับ”

แต่เรื่อง **อาหารเฉพาะโรค/ข้อจำกัดทางการแพทย์** ต้องมาจาก care plan หรือผู้เชี่ยวชาญ ไม่ให้ LLM คิด diet เอง

---

# ตอนนี้ Daily Living Agent เริ่มสำคัญเทียบกับ Health Agent แล้ว

ผมจะขยาย architecture เป็น:

```text id="f9n0k1"
                     CARE AGENT
                         │
                  CARE ORCHESTRATOR
                         │
 ┌──────────┬───────────┼───────────┬───────────┬──────────┐
 ▼          ▼           ▼           ▼           ▼          ▼
Memory    Health      Routine     Activity    Home       Safety
Agent     Agent       Agent       Agent       Agent      Agent
                                   │
                              ┌────┴─────┐
                              ▼          ▼
                           Laundry     Cooking
                              │
                         Food Inventory
                              │
                         Meal Planning
```

**Home Agent** จึงไม่ได้มีไว้แค่เปิดไฟ/ปิดแอร์ แต่เป็น **environmental memory**

```text
บ้านช่วยจำแทนผู้ป่วย
+
Agent ช่วยประสาน
+
Caregiver ช่วยเมื่อจำเป็น
```

---

## และผมคิดว่าเรามาถึงหลักการใหญ่ของโปรเจกต์แล้ว

ผู้ป่วยไม่ได้ต้องการ AI ที่ “ฉลาดที่สุด”

แต่ต้องการ AI ที่ช่วยเรื่อง:

> **“อะไรอยู่ที่ไหน / วันนี้วันอะไร / ต้องทำอะไร / ทำถึงไหนแล้ว / อะไรทำไปแล้ว / อะไรยังไม่ได้ทำ / นัดใคร / หมอสั่งอะไร / ของอะไรมีอยู่ / อะไรควรทำต่อ”**

หรือสรุปเป็น:

```text id="0q4g0f"
                    EXTERNAL MEMORY
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
       TIME              PLACE             THINGS
        │                 │                 │
     วันเวลา            อยู่ไหน          ของอยู่ไหน
        │                 │                 │
        ▼                 ▼                 ▼
      TASKS             PEOPLE            FOOD
        │                 │                 │
     ทำอะไร             พบใคร            มีอะไร
        │                 │                 │
        └─────────────────┼─────────────────┘
                          ▼
                     DAILY LIFE
                          │
                          ▼
                       CARE
```

ดังนั้น use case **อาหารที่ซื้อแล้วลืมกิน** ควรใส่เข้า roadmap ด้วย และผมจะตั้งชื่อ capability ว่า **`Home & Daily Living Memory`** เพื่อให้ต่อยอดไปถึงเสื้อผ้า อาหาร ของใช้ กุญแจ แว่น โทรศัพท์ งานบ้าน และกิจวัตรอื่น ๆ ได้ โดยไม่ต้องสร้าง Agent ใหม่ทุกเรื่องครับ
