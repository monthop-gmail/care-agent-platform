# Care Endpoint — ขอบเขตระหว่างโดเมนกับอุปกรณ์

**สถานะ:** assessment · ตอบ `task-fe9ff512` (`dis-65f4fe3e`) — ยังไม่ใช่การตัดสินใจเชิงสถาปัตยกรรม
ข้อที่ต้องตัดสินจริงจะต้องมี ADR แยก

คำถามที่ตั้งมา: เอา Smart TV มาเป็น care interaction endpoint ได้ไหม โดยไม่สร้าง care backend
ซ้ำอีกชุด · ทุกข้อด้านล่างอ้างโค้ดที่รันอยู่จริง ไม่ใช่การออกแบบบนกระดาษเปล่า

---

## A. ของที่ reuse ได้ทันที — ไม่ต้องแก้อะไรเลย

| ของที่มีอยู่ | หลักฐาน | ทำไมใช้กับ endpoint ใหม่ได้เลย |
|---|---|---|
| `register_sender(channel, sender)` | `care_escalation/services.py:40` · LINE ใช้เส้นนี้จริง (`care_line/outbound.py:36`) | **seam สำหรับ endpoint ใหม่มีอยู่แล้ว** — TV คือ sender ตัวที่สอง ไม่ต้องแตะ care loop |
| `CareNotification` | `care_escalation/models.py:46` | เก็บข้อความที่ส่งออกจริง + แยก `delivery_status` / `delivery_error` ออกจาก "บันทึกว่าส่ง" |
| `acknowledge(care_job_id, *, evidence_kind, done)` | `care_escalation/services.py:684` | **แยก "รับทราบ" ออกจาก "ทำแล้ว" ด้วย `done` อยู่แล้ว** — `done=False` ตั้ง backoff ต่อ ไม่ปิดงาน |
| `evidence.kind` ชุดปิด | `contracts/event/v1/care-event.schema.yaml:99` | `patient_confirmed` · `caregiver_confirmed` · `device_reported` · `document` · `none` |
| `external_signal()` / `awaits_external_event` | `care_activity/services.py:314` | สัญญาณจากอุปกรณ์ปิดได้ **แค่ขั้นที่รออยู่** ไม่ใช่ทั้งงาน |
| `report_signal()` | `care_safety/services.py:80` | รับสัญญาณจากอุปกรณ์พร้อม `device_id` / `confidence` / dedup ในหน้าต่างเวลา |
| orientation ครบชุด | `care_orientation/services.py` — `answer_date` · `five_layers` · `daily_brief` · `what_happens_on` · `who_is_around` | **use case 1 มีอยู่แล้วทั้งก้อน** เหลือแค่ render |
| quiet hours + severity | `care_escalation/policy.py:41` · `services.py:93` | overlay กลางดึกถูกคุมด้วยกติกาที่มีอยู่ ไม่ต้องคิดใหม่ |
| careplan · medication · approval · audit · consent · policy | ทั้งหมด | **endpoint ไม่ต้องรู้เรื่องพวกนี้เลยแม้แต่นิดเดียว** |
| intent router แบบ deterministic | [ADR-0008](../decisions/0008-patient-channel-is-deterministic.md) | รีโมท TV มีปุ่มจำกัดจำนวน — **deterministic โดยธรรมชาติ ง่ายกว่า LINE** |

> ข้อสรุปของส่วนนี้: North Star ที่ตั้งมา (*TV เป็น interface ไม่ใช่ source of truth*)
> **ตรงกับรูปที่ระบบเป็นอยู่แล้ว** ไม่ใช่สิ่งที่ต้องไปทำให้เป็น

### ข้อกังวลข้อแรกของผู้เสนอ ตอบได้ด้วยของที่มี

> *"อย่าให้ TV acknowledgement เท่ากับหลักฐานว่ากินยาแล้วโดยอัตโนมัติ"*

มีสามชั้นแยกกันอยู่แล้ว และไม่มีชั้นไหนไหลเข้าหาอีกชั้นเอง:

```text
delivery_status = sent        ส่งถึงจอแล้ว              ← ไม่ใช่หลักฐานอะไรเลย
evidence.kind   = device_reported   อุปกรณ์รายงานเหตุการณ์   ← ไม่ใช่คำยืนยันของคน
evidence.kind   = patient_confirmed  คนกดยืนยันว่าทำแล้ว     ← หลักฐานเดียวที่ปิดงานได้
```

[ADR-0006 ข้อ 5](../decisions/0006-ai-has-no-medical-authority.md) บังคับไว้อีกชั้นว่า
ไม่มีหลักฐาน = **ตอบว่าไม่มีหลักฐาน** ห้ามเดาจาก pattern หรือเวลาที่ผ่านไป

---

## B. gap ที่เป็นของโดเมน — ควรอยู่ใน care-agent-platform

**1. `channels` ยังไม่มีชุดปิด**
`care_patient/models.py:36` เป็น `JSON` list ที่ default `["app"]` และไม่มีอะไรตรวจว่าค่านั้นคือ
ช่องทางที่ระบบรู้จัก · เพิ่ม `"tv"` วันนี้ก็ได้ และพิมพ์ `"tvv"` ก็ได้เหมือนกัน
→ ควรเป็น vocabulary ปิดแบบเดียวกับ `kind` / `category` ที่โดเมนอื่นใช้
**แผลเดิมของ repo นี้คือ allowlist ที่สะกดผิดแล้วเงียบมาหนึ่งเดือน** ([ADR-0011](../decisions/0011-audit-holds-pointers-not-content.md))

**2. ไม่มี presentation intent ในโดเมน**
`CareNotification.text` เป็นข้อความเดียว · ไม่มีที่บอกว่า overlay หรือเต็มจอ · ต้องอ่านออกเสียงไหม ·
ต้องรอคนกดตอบไหม · ค้างบนจอได้นานแค่ไหน
→ ต้องเป็น **ฟิลด์เชิงโครงสร้าง** ไม่ใช่ฝัง markup ลงใน `text`
(และตาม ADR-0011 ค่าเหล่านั้นต้องเป็น `code` ไม่ใช่ข้อความเสรี)

**3. ไม่มี capability สำหรับ "การกระทำต่ออุปกรณ์" เลยแม้แต่ตัวเดียว**
ทั้ง 29 capability ในวันนี้เป็น **notify · record · propose** ทั้งหมด
`policies/care-authority-map.yaml` ไม่มีตัวไหนที่ **เปลี่ยนสภาพแวดล้อมของผู้ป่วย**
→ `media.playback.pause` เป็น action **ชนิดใหม่ของระบบนี้** ไม่ใช่ capability ที่เพิ่มต่อจากของเดิม
ข้อนี้ต้องมี ADR ก่อนเขียนโค้ด ไม่ใช่เพิ่มบรรทัดใน YAML

**4. "แสดงบนจอแล้ว" ยังไม่มีที่อยู่ที่ถูก**
`delivery_status` ที่มีคือ `pending` / `sent` / `failed` / `stored` ซึ่งพูดถึง *ช่องทาง*
ไม่ได้พูดถึงว่า *คนเห็นหรือยัง* · TV รู้เพิ่มได้ว่าจอเปิดอยู่ไหม แอปอยู่หน้าไหน
→ ถ้าจะเก็บ ต้องชัดว่ามันไม่ใช่ `evidence` และไม่มีทางกลายเป็น evidence

**5. ⚠️ use case "media intervention" ชนข้อจำกัดที่เราประกาศไว้เอง**
การเตือนหลังดูทีวีนาน ต้องเก็บ **พฤติกรรมการดูทีวีของผู้ป่วย** ซึ่งเป็นข้อมูลชนิดใหม่
ที่ระบบนี้ไม่เคยเก็บ

`platform-contract.yaml` กับ `task-4c4a109f` ประกาศไว้ว่า **ไม่ขยายการเก็บข้อมูลสุขภาพเพิ่ม
จนกว่าจะมีคำตอบทางกฎหมายเรื่อง audit ที่ลบไม่ได้** — ใบนั้นยัง `blocked` ไม่มีกำหนด

| use case | ชนข้อจำกัดไหม |
|---|---|
| 1 orientation · 2 medication reminder · 3 activity prompt · 5 caregiver escalation | **ไม่ชน** — ใช้ข้อมูลที่เก็บอยู่แล้ว เปลี่ยนแค่ช่องทางแสดง |
| 4 media intervention | **ชน** — เป็นการเก็บข้อมูลใหม่เกี่ยวกับผู้ป่วย |

→ ข้อ 4 แยกออกจากรอบแรกได้โดยไม่กระทบข้ออื่น และควรแยก

---

## C. ของที่ควรอยู่ใน adapter แยก — ไม่ใช่ใน care-agent-platform

Android TV SDK · TrueID · overlay rendering · เสียง TTS · การ map ปุ่มรีโมท ·
app lifecycle · การจับคู่อุปกรณ์กับ token

เหตุผลไม่ใช่ความสะอาด แต่เป็น [ADR-0002](../decisions/0002-runtime-on-pstack.md) กับ
[ADR-0003](../decisions/0003-conformance-layer-in-app-repo.md): ของที่ผูกกับ vendor
ห้ามเข้าแกนกลาง · และ `register_sender` ถูกออกแบบมาเพื่อสิ่งนี้อยู่แล้ว
**LINE เป็นหลักฐานว่ามันทำงานจริงกับ endpoint ที่ไม่ใช่ของเรา**

### หน้าตัดที่เสนอ — สี่ทาง ซึ่งสามทางมีอยู่แล้ว

| ทาง | สถานะวันนี้ | ของที่ใช้ |
|---|---|---|
| **present** (ออก) | ✅ มีแล้ว | `register_sender("tv", …)` + `CareNotification` |
| **acknowledge** (เข้า) | ✅ มีแล้ว | `acknowledge(care_job_id, evidence_kind=…, done=…)` |
| **device signal** (เข้า) | ✅ มีแล้ว | `external_signal()` · `report_signal()` |
| **device action** (ออก) | ❌ **ยังไม่มี** | ต้องออกแบบ — ดูข้อ B.3 |

---

## ที่อยู่ของ implementation ที่เสนอ

**โมดูล `care_endpoint` ใน repo นี้** ถือของที่เป็นคำถามของโดเมน — ใครควรเห็นอะไร ตอนไหน
ด่วนแค่ไหน ต้องรอคำตอบไหม · บวก vocabulary ของช่องทาง และ capability ของ device action

**`care-tv-adapter` แยก repo** ถือของที่เป็นคำถามของอุปกรณ์ — วาดยังไง พูดยังไง ปุ่มไหน

เส้นแบ่งที่ใช้ตัดสินว่าอะไรอยู่ฝั่งไหน: **ถ้าเปลี่ยนยี่ห้อ TV แล้วต้องแก้ มันอยู่ฝั่ง adapter**

---

## ข้อควรระวังที่ผู้เสนอตั้งไว้ — เทียบกับของที่มี

| ข้อที่ตั้งไว้ | สถานะ |
|---|---|
| TV ack ≠ หลักฐานว่ากินยาแล้ว | ✅ มีสามชั้นแยกกันอยู่แล้ว (ดูข้อ A) |
| AI ห้ามเปลี่ยนยา/ตารางยาเอง | ✅ `medication.regimen.write` เป็น `high` + อยู่ใน `tools.deny` ของ profile |
| privileged/device action ต้องผ่าน policy/approval | ⚠️ กลไกมี แต่ **ยังไม่มี capability ให้ผูก** (ข้อ B.3) |
| stopping/cancel ไม่ควรถูก approval ขวาง | ✅ หลักนี้เราเป็นคนเสนอเองที่ `dis-a84b7a8e` และมีรูปรองรับแล้วคือ `audited_exception` ใน `ap_policy` |
| ห้ามใช้ข้อมูลผู้ป่วยจริงใน workspace | ✅ เอกสารนี้ไม่มีข้อมูลผู้ป่วย |

`audited_exception` สำคัญกับ TV มากกว่าที่คิด: **`pause` ต้องไม่รอใครอนุมัติ** และ
`resume` ต้องไม่ง่ายกว่า `pause` — ซึ่งเป็นเส้นแบ่งเดียวกับ
[ADR-0029 ของ agent-platform ข้อ 1a](https://github.com/monthop-gmail/agent-platform/blob/main/decisions/0029-the-cost-of-not-acting.md)
ที่เราเป็นผู้ผลิตรายแรกของมัน

---

# ภาคผนวก — ความพร้อมก่อน implement

เพิ่มเมื่อ 2026-09-27 ตอบ `task-7538109a` ข้อ 2–5 · ตัดสินใจอยู่ที่
[ADR-0014](../decisions/0014-presentation-intent-is-a-request-not-a-command.md) กับ
[ADR-0015](../decisions/0015-device-actions-touch-the-real-world.md) · ที่นี่เป็นของที่ตามมาจากสองใบนั้น

## รูป contract ที่ `care_endpoint` จะ consume

```yaml
# ขาออก — sender ได้ notification ทั้งก้อนเหมือนเดิม + presentation ที่เป็น optional
notification:
  text: str                     # สิ่งที่ผู้ป่วยได้อ่าน — ไม่มี markup (ADR-0014 ข้อ 1)
  channel: code                 # จาก vocabulary ปิด (precondition — ดูด้านล่าง)
  severity: code
  presentation:                 # optional · ทุกค่าเป็น code
    surface: overlay | full_screen | ambient
    speak: bool
    response: required | optional | none
    dwell: short | medium | until_answered

# ขาเข้า — ไม่มีของใหม่ ใช้ของที่มีอยู่ทั้งสามทาง
acknowledge(care_job_id, *, evidence_kind, done)        # care_escalation/services.py:684
external_signal(...)                                    # care_activity/services.py:314
report_signal(...)                                      # care_safety/services.py:80

# ขาออกชนิดใหม่ — device action (ADR-0015)
media.playback.pause | .cancel | .resume
```

`presented` เป็นสถานะของ **notification** ไม่ใช่ของงาน · อยู่ข้าง `delivery_status`
ไม่ใช่ข้าง `evidence` — ข้อนี้เป็นเรื่องของ**ที่อยู่** ไม่ใช่แค่การตั้งชื่อ (ADR-0014 ข้อ 5)

## ผลต่อของที่มีอยู่ และความเข้ากันได้ย้อนหลัง

| ของที่มี | กระทบไหม |
|---|---|
| `register_sender()` / sender ของ LINE | **ไม่กระทบ** · `presentation` เป็น optional และ `care_line/outbound.py:20` อ่านแค่ `text` กับ `channel` |
| `CareNotification` | เพิ่มคอลัมน์ optional · migration แบบ additive · แถวเดิมอ่านได้เหมือนเดิม |
| `acknowledge()` | ไม่แตะ signature · TV ใช้ตัวเดียวกับ LINE |
| careplan / medication / escalation / approval / audit | ไม่แตะเลย |
| `care_patient.channels` | ⚠️ **precondition** — ต้องปิดเป็น vocabulary ก่อน (`models.py:36` วันนี้รับอะไรก็ได้) |

**precondition ข้อเดียวที่ต้องทำก่อนทุกอย่าง** คือ `channels` เพราะถ้าไม่ปิด
`"tvv"` จะกลายเป็นช่องทางที่ไม่มี sender แล้ว `_deliver()` จะตั้ง `delivery_status = "stored"`
เงียบ ๆ (`care_escalation/services.py:315`) — คือข้อความไม่ถึงใครโดยไม่มีใคร error
ซึ่งเป็น fail-closed ที่เงียบ แบบเดียวกับที่เราเจอกับเพดานของ agent

## ตัวตรวจที่จะบังคับสัญญานี้

| ข้อที่ต้องบังคับ | บังคับด้วยอะไร | มีอยู่แล้วไหม |
|---|---|---|
| ค่าใน `presentation` เป็น code จากชุดปิด | ทะเบียนใน `ap_audit/attributes.py` + `emit()` reject | ✅ กลไกมีแล้ว เพิ่มคีย์ |
| ไม่มี code path ไหนแปลง delivery/presented → evidence | AST scan แบบเดียวกับ `REASON_INTERPOLATIONS` (`tests/test_audit_attributes.py`) | ✅ รูปมีแล้ว เขียนตัวใหม่ |
| `channels` เป็นชุดปิด | test แบบเดียวกับ `CATEGORIES` / `KINDS` ของโดเมนอื่น | ✅ รูปมีแล้ว |
| `resume` ไม่ต่ำกว่า `notify` และไม่เป็น audited exception | `floor.capabilities` + `profile_check` | ✅ `floor` มีแล้ว · เพิ่มหนึ่งบรรทัด |
| `pause` ไม่ถูก approval ขวาง | `ap_policy/engine.py:291` — เพดาน profile ยกทับ audited exception ไม่ได้ | ✅ บังคับอยู่แล้ว |
| ไม่มี `undoes` ผิดทิศ | `load_policy()` boot ไม่ผ่าน + `profile_check` ข้อ 7 | ✅ บังคับอยู่แล้ว |
| payload ของ endpoint conform | `payload_check` หลังมี schema จริง | ⏳ ตามมากับ implementation |

**หกในเจ็ดข้อบังคับได้ด้วยกลไกที่มีอยู่แล้ว** — ไม่ต้องสร้างชั้นตรวจใหม่

## พร้อมแตก implementation task หรือยัง

**พร้อม สำหรับสามข้อ · ยังไม่พร้อม สำหรับข้อที่สี่**

| ลำดับ | งาน | สถานะ |
|---|---|---|
| 0 | ปิด `channels` เป็น vocabulary + test | ✅ พร้อม · เล็ก · เป็น precondition ของทุกข้อ |
| 1 | `presentation` บน `CareNotification` + ทะเบียนคีย์ + AST ratchet กัน evidence | ✅ พร้อม · ADR-0014 ตัดสินรูปครบแล้ว |
| 2 | capability สามตัวของ `media.playback.*` + `floor` + profile `deny` ที่ควรมี | ✅ พร้อม · ADR-0015 ตัดสินระดับความเสี่ยงครบแล้ว |
| 3 | `care-tv-adapter` (`register_sender("tv", …)` + rendering + remote) | ✅ พร้อม แต่เป็นงานคนละ repo |
| 4 | media intervention ตามพฤติกรรมการดูทีวี | ❌ **ยังไม่พร้อม** — ต้องเก็บข้อมูลชนิดใหม่ · รอ `task-4c4a109f` |

ข้อ 4 ไม่ได้ติดที่เทคนิค และไม่ได้ติดที่การออกแบบ · ติดที่ข้อจำกัดที่ repo นี้ประกาศไว้เอง
ว่าไม่ขยายการเก็บข้อมูลสุขภาพจนกว่าจะมีคำตอบทางกฎหมาย

> ข้อ 0–3 ไม่ต้องรอข้อ 4 และข้อ 4 ไม่ทำให้ข้อ 0–3 ต้องออกแบบต่างไป
> เพราะ `pause` ตัวเดียวกันใช้ได้ทั้งสองแบบ ต่างกันแค่ว่า**อะไรเป็นคนสั่ง**
