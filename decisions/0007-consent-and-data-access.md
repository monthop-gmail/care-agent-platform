# ADR-0007: consent เป็นเงื่อนไขการเข้าถึง ไม่ใช่แค่ RBAC

**Status:** Accepted (2026-08-18)
**Depends on:** [ADR-0003](0003-conformance-layer-in-app-repo.md)

## Context

pstack มี RBAC แบบ role → permission string ซึ่งตอบได้แค่ "ผู้ใช้คนนี้ทำ action นี้ได้ไหม"
แต่โดเมนนี้ต้องตอบคำถามที่แคบกว่านั้น:

> ลูกสาวดู **ตำแหน่ง** ของแม่ได้ไหม · ดู **ผลเลือด** ได้ไหม · ได้ถึงเมื่อไร · ใครอนุญาต

blueprint (`ref` §14) ระบุ consent เป็น 5 มิติ: **who → can access → which data → for what purpose → for how long**
และผู้ป่วยที่มีภาวะความจำเสื่อมเป็นกลุ่มเปราะบางเป็นพิเศษ — ความยินยอมอาจถูกให้โดยผู้มีอำนาจแทน
ซึ่งยิ่งต้องบันทึกให้ชัดว่าใครให้ความยินยอมแทนและเมื่อไร

## Decision

### 1. การเข้าถึงข้อมูลผู้ป่วยต้องผ่านสองด่านเสมอ

```
request → RBAC (pstack: ทำ action นี้ได้ไหม) → consent (ap_tenancy: กับผู้ป่วยคนนี้ ข้อมูลชุดนี้ ตอนนี้ ได้ไหม) → data
```

ผ่านด่านแรกด่านเดียวไม่พอ — caregiver ที่มี `care.patient.read` อ่านได้เฉพาะผู้ป่วยที่ตัวเองมี consent เท่านั้น

### 2. consent grant เป็นข้อมูลชัดเจน ไม่ใช่ implicit จากความสัมพันธ์

```yaml
grantee: caregiver:daughter-01        # ใคร
patient: patient-004                  # ของผู้ป่วยคนไหน
scopes: [routine.read, medication.read, location.read]   # ข้อมูลชุดไหน
purpose: daily_care                   # เพื่ออะไร
granted_by: patient-004               # ใครเป็นคนอนุญาต (หรือผู้มีอำนาจแทน)
granted_at: ...
expires_at: ...                       # ถึงเมื่อไร (null = จนกว่าจะเพิกถอน)
```

- **การเป็น "ลูกสาว" ไม่ให้สิทธิ์อะไรโดยอัตโนมัติ** — ต้องมี grant เสมอ
- ถอนได้ทุกเมื่อ (`revoked_at`) และการถอนมีผลทันที ไม่ใช่รอ session หมดอายุ
- grant, การใช้ และการถอน ออก audit event ทุกครั้ง

### 3. scope แยกตามความอ่อนไหว ไม่ใช่ก้อนเดียว

`routine` · `meal` · `medication` · `appointment` · `journal` · `location` · `clinical`

`location` และ `clinical` เป็นคนละเรื่องกับ `routine` — ครอบครัวส่วนใหญ่ควรได้แค่ชุดแรก
default ของทุก grant ใหม่คือ **ไม่ได้อะไรเลย** ต้องเลือกทีละ scope

### 4. tenant isolation อยู่เหนือ consent

consent ข้าม tenant ไม่ได้ ไม่ว่ากรณีใด — ถ้าผู้ป่วยย้ายจาก "ครอบครัว B" ไป "โรงพยาบาล A"
คือการสร้างข้อมูลใน tenant ใหม่พร้อม consent ใหม่ ไม่ใช่การแชร์ข้าม tenant
(invariant ของ `identity/v1`: tenant เป็นขอบเขต isolation แข็ง ห้ามข้ามเด็ดขาด)

### 5. escalation ไม่ข้าม consent แต่มีทางออกที่บันทึกได้

กรณีฉุกเฉิน (`critical`) ระบบแจ้ง contact ฉุกเฉินได้แม้ scope ไม่ครอบคลุม
แต่ต้อง: ส่งเฉพาะข้อมูลเท่าที่จำเป็นต่อการช่วยเหลือ · ออก event `care.escalated`
พร้อม `policy_result` ที่ระบุว่าใช้ข้อยกเว้นนี้ · และแจ้งผู้ป่วย/ผู้ดูแลหลักย้อนหลังเสมอ
— **ห้ามใช้ข้อยกเว้นนี้กับ severity ต่ำกว่า critical**

## Consequences

- ทุก query ที่อ่านข้อมูลผู้ป่วยต้องผ่าน helper ของ `ap_tenancy` — ห้าม `select(Patient)` ตรง ๆ ใน `care_*`
  (มี test บังคับ + review ของทีม A)
- ต้องมีหน้าจัดการ consent ที่ caregiver/ผู้ป่วยเข้าใจได้ ไม่ใช่ config ของ admin เท่านั้น
- รองรับ PDPA ได้ตั้งแต่ต้น: ตอบได้ว่าใครเข้าถึงข้อมูลอะไรเมื่อไร และลบ/ถอนได้จริง
- เพิ่มงานให้ทุกทีมเล็กน้อยในทุก endpoint — ยอมรับ เพราะย้อนกลับมาใส่ทีหลังแพงกว่ามาก

## Sources

[`ref/chatgpt-care-agent-design.md`](../ref/chatgpt-care-agent-design.md) §13, §14 ·
[agent-platform `contracts/identity/v1`](https://github.com/monthop-gmail/agent-platform/blob/main/contracts/identity/v1/identity.schema.yaml) ·
[agent-platform ADR-0007](https://github.com/monthop-gmail/agent-platform/blob/main/decisions/0007-multi-tenancy.md)
