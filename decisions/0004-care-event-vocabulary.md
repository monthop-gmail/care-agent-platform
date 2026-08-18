# ADR-0004: care event vocabulary ต่อยอดจาก `event/v1` แบบ additive

**Status:** Accepted (2026-08-18)
**Depends on:** [ADR-0001](0001-consumer-of-agent-platform.md)

## Context

`event/v1` ของ `agent-platform` ระบุว่า `EventType` เป็น **ชุดเปิด** — 7 ค่าคือขั้นต่ำที่ต้องมี
"เพิ่ม event type ใหม่ = additive · ทำได้เองผ่าน ADR ที่ repo ผู้ใช้ · ลดทอน guarantee ข้อใดไม่ได้"

ส่วน `SubjectType` เป็นชุดปิดของ platform: `[job, execution, step, agent, tool_call, artifact, approval, external]`
ซึ่งไม่มี `patient` / `medication` — เราจึงต้องตัดสินว่าจะ map โดเมนเราเข้ากับชุดนี้อย่างไร

## Decision

### 1. map care loop เข้ากับ subject ของ platform (ไม่แตะ `SubjectType`)

หนึ่ง "รอบการดูแล" (เตือน → ยืนยัน → retry → escalate) คือ **job** หนึ่งตัว และแต่ละครั้งที่ลงมือคือ **execution**

| สิ่งที่เกิดขึ้นจริง | subject_type | event_type ของ platform |
|---|---|---|
| ถึงเวลาต้องเตือนกินยา → สร้างรอบการดูแล | `job` | `JOB_CREATED` |
| ส่ง reminder ครั้งที่ n | `execution` | `EXECUTION_STARTED` |
| รอบนี้เปลี่ยนสถานะ (pending → acknowledged) | `job` | `STATE_TRANSITION` |
| policy ตัดสินว่า escalate ได้ไหม | `job` | `GOVERNANCE_DECISION` |
| ส่งไม่ออก / ช่องทางล่ม | `execution` | `EXECUTION_FAILED` |
| จบรอบ (ยืนยันแล้ว หรือ escalate จนสุดทาง) | `job` | `JOB_COMPLETED` |
| event จาก IoT / wearable / โรงพยาบาล | `external` | ตามชนิด + `source.kind: external` |

`subject_id` ของ job คือ `care_job_id` ส่วนสิ่งที่โดนกระทำจริง (patient, medication version)
อยู่ใน `attributes` — **ห้ามสร้าง `job_id` ปลอมให้ event ที่ไม่ได้เกิดจาก job** (invariant ของ platform)

**บันทึกของโดเมนที่ไม่ได้เกิดจาก job** (สร้างผู้ป่วย · medication version ใหม่ · journal entry)
ใช้ `subject_type: record` โดย `subject_id` คือ id ของบันทึกนั้น และระบุชนิดไว้ที่
`attributes.record_type` — platform ไม่รู้จักชนิดของโดเมนและไม่ควรรู้

> **อัปเดต 2026-08-19** — เดิมข้อนี้ใช้ `artifact` เพราะ `SubjectType` เป็นชุดปิดที่ไม่มีค่าที่ตรง
> ซึ่งทำให้ audit แยกไม่ออกระหว่าง "ของที่ execution ผลิต" กับ "บันทึกที่มีอยู่จริงในโลก"
> เราเปิด [agent-platform#14](https://github.com/monthop-gmail/agent-platform/issues/14)
> และ platform เพิ่มค่า `record` ให้แล้ว (`8f7dd13`) — ย้ายมาใช้ค่าที่ตรงกว่าเรียบร้อย
>
> ข้อควรระวังที่ต้นทางฝากไว้: ถ้าวันหนึ่ง `metadata.record_type` กลายเป็นสิ่งที่ **policy
> ตัดสินใจจากมัน** (ไม่ใช่แค่ป้ายกำกับใน audit) นั่นคือการเปลี่ยนความหมายของ `record`
> ซึ่งเข้า Rule 2 ของ ADR-0006 และต้องมี RFC ที่ต้นทางก่อน

### 2. เพิ่ม care event type แบบ additive

```
care.reminder.sent            care.meal.confirmed          care.appointment.reminded
care.reminder.acknowledged    care.meal.missed             care.appointment.prep_step_done
care.reminder.missed          care.medication.confirmed    care.appointment.completed
care.escalated                care.medication.missed       care.journal.recorded
care.observation.recorded     care.medication.changed      care.question.recorded
care.task.step_completed      care.medication.conflict     care.plan.task_completed
care.task.stalled             care.orientation.delivered   care.deviation.detected
```

**กฎการตั้งชื่อ:** `care.<โดเมน>.<สิ่งที่เกิดขึ้นแล้ว>` — เป็นอดีตเสมอ (สังเกตการณ์ ไม่ใช่คำสั่ง)

### 3. ข้อห้ามที่มาจาก guarantee ของ platform (ลดทอนไม่ได้)

- **append-only** — แก้/ลบ event ไม่ได้ ต่อให้บันทึกผิด ให้ออก event แก้ตัวใหม่แทน
- **no silent state change** — ทุกการเปลี่ยนสถานะของ job/task/medication ต้องมี event เสมอ
- **event ที่ resolve tenant ไม่ได้ ให้ reject ที่ intake** — ห้ามเดา tenant ให้
- **external event ต้องคง `source` ไว้ตลอดไป** — event จากนาฬิกา/เซนเซอร์ต้องรู้ว่ามาจากข้างนอก
- **ห้ามเก็บ chain-of-thought ของ LLM เป็น audit record** — เก็บ structured metadata แทน
- consumer ที่เจอ `event_type` ที่ไม่รู้จัก **ต้องเก็บไว้แล้วข้ามการตีความ ห้าม drop ห้าม fail**

### 4. `care.deviation.detected` คือการสังเกต ไม่ใช่การวินิจฉัย

payload มีได้แค่ข้อเท็จจริงที่วัดได้ (`expected_at`, `observed`, `delta_minutes`, `baseline_days`)
**ห้ามมี field ที่แปลผลทางการแพทย์** เช่น `condition`, `diagnosis`, `severity_of_illness`
— `severity` ที่มีได้คือความเร่งด่วนของการแจ้งเตือน ไม่ใช่ความรุนแรงของโรค

## Consequences

- `ap_audit` เป็นที่เดียวที่เขียน event ได้ — `care_*` เรียกผ่าน service ห้าม insert ตารางตรง
- เพิ่ม event type ใหม่ = แก้ `contracts/event/v1/care-event.schema.yaml` + ADR สั้น ๆ ไม่ต้องขอ platform
- dashboard/รายงานทั้งหมดสร้างจาก event ไม่ใช่จาก state ปัจจุบัน — ตอบ "ทำไม agent ถึงส่งข้อความนี้" ย้อนหลังได้

## Sources

[agent-platform `contracts/event/v1`](https://github.com/monthop-gmail/agent-platform/blob/main/contracts/event/v1/event.schema.yaml) ·
[`ref/chatgpt-care-agent-design.md`](../ref/chatgpt-care-agent-design.md) §16, §17
