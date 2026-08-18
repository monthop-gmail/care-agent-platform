# ADR-0006: AI ไม่มี medical authority — บังคับผ่าน authority_map

**Status:** Accepted (2026-08-18)
**Depends on:** [ADR-0003](0003-conformance-layer-in-app-repo.md)

## Context

หลักการ 7 ข้อจาก blueprint (`ref` §27) — **AI ≠ Doctor · AI ≠ Authority · Observation ≠ Diagnosis ·
Personal Memory ≠ Medical Truth · high-risk ต้องมี governance · ทุก action ต้อง audit ได้ ·
data ต้อง tenant/consent aware**

ปัญหาคือหลักการที่เขียนไว้ใน README ไม่มีผลบังคับ ถ้าโค้ดยังเรียก LLM แล้วเขียน DB ได้ตรง ๆ
เราจึงต้องแปลงหลักการเป็นกลไกที่ **ผิดแล้วพัง** ไม่ใช่ **ผิดแล้วต้องหวังว่าจะมีคนรีวิวเจอ**

`agent-platform` ADR-0010 ให้เครื่องมือไว้แล้ว: `action_risk` (static ผูกกับ capability)
× `authority_map` (config ต่อ tenant) → `authority` ∈ `auto / notify / approval_required / human_command_required`

## Decision

### 1. ทุก action ที่แตะโลกจริงต้องประกาศ `action_risk` และผ่าน `ap_policy` เสมอ

```python
@care_action(action_risk="high", capability="medication.regimen.write")
async def create_medication_version(...): ...
```

action ที่ไม่ประกาศ `action_risk` → runtime **ปฏิเสธ** (fail closed) ไม่ใช่ default เป็น low

### 2. authority_map เริ่มต้นของ care profile

| action | risk | authority | เหตุผล |
|---|---|---|---|
| ส่ง reminder กิจวัตร/อาหาร/นัด | low | `auto` | ผิดพลาดแล้วเสียหายน้อย |
| บันทึก journal / คำถามถึงหมอ | low | `auto` | เป็นการจดของผู้ป่วยเอง |
| แจ้ง caregiver ว่าพลาดมื้อ/ยา | medium | `notify` | ทำได้เลยแต่ต้องมีบันทึกว่าใครถูกแจ้ง |
| แก้ care plan (ออกกำลัง/ดื่มน้ำ) | medium | `approval_required` | มาจากคำสั่งหมอ คนต้องยืนยันว่าตรง |
| **สร้าง/แก้ medication version** | high | `human_command_required` | AI เสนอได้อย่างเดียว คนต้องเป็นผู้สั่ง |
| **หยุดยา / เปลี่ยนขนาด** | critical | `human_command_required` | ห้าม auto เด็ดขาดทุก tenant |
| ประกาศภาวะฉุกเฉิน | critical | `notify` + escalate ทันที | ความเร็วสำคัญกว่า แต่ต้อง audit ครบ |

**map นี้เป็น config** (`policies/care-authority-map.yaml`) — tenant แก้ให้เข้มขึ้นได้
แต่ **แก้ให้หลวมกว่าเพดานไม่ได้**: `medication.regimen.write` · `medication.regimen.stop`
และ `critical` ทุกตัวถูก freeze ไว้ที่ `human_command_required` ถ้า config พยายามลดกว่านี้
ให้ boot ไม่ผ่าน

⚠️ เพดานต้องเจาะจงที่ **การเขียนใบยา** ไม่ใช่ `medication.*` ทั้งก้อน — ไม่งั้นการ
*เตือนกินยา* (low/auto) และการ *เสนอ* คำสั่งใหม่ (medium) จะติดเพดานไปด้วย
แล้วระบบจะเตือนกินยาไม่ได้เลย มี scenario test กันความผิดพลาดนี้ไว้

### 3. LLM เขียน DB ไม่ได้เลย

agent เรียกได้เฉพาะ tool ที่ลงทะเบียนไว้ และ tool ที่เขียนข้อมูลทางการแพทย์จะ
**สร้างเป็น proposal เท่านั้น** (`status: proposed`) จนกว่าจะมีคนกดยืนยัน

```
หมอบอกหน้าห้องตรวจ → agent ถอดความ → proposal → คน/caregiver ยืนยัน → version ใหม่ → audit
                                        ▲
                                 ค้างอยู่ตรงนี้ได้ตลอดกาล — ไม่มี timeout ที่ auto-approve
```

### 4. Observation ≠ Diagnosis บังคับที่ระดับ schema

ระบบพูดได้ว่า "วันนี้ยังไม่มีบันทึกว่าทานยาเช้า" — พูดไม่ได้ว่า "ผู้ป่วยอาการแย่ลง"
ห้ามมี field ที่แปลผลทางการแพทย์ในทุก contract ของโดเมนนี้ (ดู [ADR-0004](0004-care-event-vocabulary.md) ข้อ 4)

### 5. ไม่มีหลักฐาน = ตอบว่าไม่มีหลักฐาน

ถ้าผู้ป่วยถาม "กินยาแล้วยัง" แล้วไม่มี event ยืนยัน ระบบต้องตอบว่า **ยังไม่มีข้อมูล**
ห้ามเดาจาก pattern ปกติ ห้ามอนุมานจากเวลาที่ผ่านไป — นี่คือเส้นแบ่งระหว่าง
"ผู้ช่วยความจำ" กับ "แหล่งข้อมูลที่ผู้ป่วยเชื่อแล้วกินยาซ้ำ"

## Consequences

- ทุก addon ต้องมี test ที่พิสูจน์ว่า action ของตัวเองถูก policy ปฏิเสธเมื่อไม่มี authority
- ฟีเจอร์ "agent ฟังหมอแล้วอัปเดตยาให้อัตโนมัติ" จะไม่มีวันได้ทำ — และนี่คือความตั้งใจ
- UX ต้องออกแบบให้การยืนยันของคนเป็นเรื่องง่าย (กดปุ่มเดียวใน LINE) ไม่งั้นคนจะเลี่ยงระบบ
- ถ้าวันหนึ่งมี requirement ให้ auto-approve อะไรที่ risk สูง ต้องเขียน ADR ใหม่ที่ supersede ตัวนี้
  และต้องมี clinical authority เซ็นรับผิดชอบ ไม่ใช่ decision ระดับทีมพัฒนา

## Sources

[`ref/chatgpt-care-agent-design.md`](../ref/chatgpt-care-agent-design.md) §5, §12, §27 ·
[agent-platform ADR-0010](https://github.com/monthop-gmail/agent-platform/blob/main/decisions/0010-risk-approval-taxonomy.md)
