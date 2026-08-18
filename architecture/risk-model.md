# Risk & Escalation Model

บังคับใช้ผ่าน [ADR-0006](../decisions/0006-ai-has-no-medical-authority.md) และ `ap_policy`

## สองคำที่ห้ามสับสน

| คำ | คืออะไร | ผูกกับอะไร |
|---|---|---|
| `action_risk` | ความเสียหายถ้าทำผิด | **static** ผูกกับ capability/tool ไม่ใช่กับ request |
| `authority` | ใครต้องอนุมัติก่อนลงมือ | ผลของ `action_risk × authority_map` ของ tenant |
| `severity` | ความเร่งด่วนของเหตุการณ์ | โดเมนกำหนดเอง — **ไม่ใช่ความรุนแรงของโรค** |

## ระดับ risk

| ระดับ | ตัวอย่าง |
|---|---|
| `low` | reminder กิจวัตร/อาหาร/นัด · บันทึก journal · ตอบคำถาม orientation |
| `medium` | แจ้ง caregiver ว่าพลาดมื้อ/ยา · แก้ care plan · บันทึกกิจกรรมแทนผู้ป่วย |
| `high` | สร้าง/แก้ medication version · ส่งข้อมูล clinical ออกนอกระบบ |
| `critical` | หยุดยา/เปลี่ยนขนาด · ประกาศภาวะฉุกเฉิน · เข้าถึงข้อมูลนอก consent |

## authority

```
auto                      ทำได้เลย
notify                    ทำได้เลย แต่ต้องแจ้งและบันทึกว่าแจ้งใคร
approval_required         ต้องมีผู้มีอำนาจอนุมัติก่อน
human_command_required    AI เสนอได้อย่างเดียว คนต้องเป็นผู้สั่ง
```

ค่าที่ไม่รู้จัก → fallback เป็น `human_command_required` (fail closed ตาม `policy/v1`)

## เพดานที่ config แก้ไม่ได้

tenant ตั้งให้ **เข้มขึ้น** ได้เสมอ แต่ลดต่ำกว่านี้ไม่ได้ — boot ไม่ผ่านถ้าพยายาม:

```
medication.regimen.write  ≥ human_command_required
medication.regimen.stop   ≥ human_command_required
critical ทุกตัว            ≥ human_command_required  (ยกเว้น emergency escalation = notify + audit เต็ม)
```

⚠️ เพดานต้องเจาะจงที่การ *เขียน* ใบยา — ตั้งเป็น `medication.*` เมื่อไร การเตือนกินยา
(`medication.reminder.send`, low/auto) จะติดเพดานไปด้วยและระบบจะเตือนไม่ได้เลย

## escalation ladder

```
severity: low       → บันทึกอย่างเดียว ไม่รบกวนใคร
severity: medium    → เตือนผู้ป่วยซ้ำตาม policy → ถ้ายังไม่ตอบ แจ้ง caregiver
severity: high      → แจ้ง caregiver ทันที + ติดตามจนกว่าจะมีคนรับ
severity: critical  → แจ้งทุกช่องทาง + contact ฉุกเฉิน (ข้าม consent ได้เฉพาะระดับนี้)
```

**กันไม่ให้กลายเป็น notification storm:**
- reminder ซ้ำมี backoff และเพดานต่อรอบ (config ต่อ tenant)
- หลาย event ของ job เดียวกัน → รวมเป็นการแจ้งครั้งเดียว (correlation_id)
- daily summary ใช้แทนการแจ้งทีละเรื่องสำหรับ severity ต่ำ
- ถ้า caregiver รับเรื่องแล้ว (`acknowledged`) หยุดเตือนทันที

## สิ่งที่ระบบพูดได้ / พูดไม่ได้

การแจ้ง caregiver ทุกข้อความต้องเป็น **ข้อเท็จจริงที่วัดได้**:

```
พูดได้     "วันนี้มีงานที่เริ่มแล้วแต่ยังไม่เสร็จ 3 รายการ"
พูดไม่ได้  "ผู้ป่วยมีอาการแย่ลง"

พูดได้     "ยังไม่มีบันทึกว่าทานยาเช้า (ครบกำหนด 08:00 · ตอนนี้ 09:30)"
พูดไม่ได้  "ผู้ป่วยลืมกินยา"    ← เดาสาเหตุ
```

`care.deviation.detected` มีได้แค่ `expected_at` / `observed` / `delta_minutes` / `baseline_days`
— ห้ามมี field ที่แปลผลทางการแพทย์ ([ADR-0004](../decisions/0004-care-event-vocabulary.md) ข้อ 4)
