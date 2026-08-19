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
request → RBAC (pstack: ทำ action นี้ได้ไหม) → consent (ap_consent: กับผู้ป่วยคนนี้ ข้อมูลชุดนี้ ตอนนี้ ได้ไหม) → data
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

- ทุก query ที่อ่านข้อมูลผู้ป่วยต้องผ่าน `scoped()` ของ `core.tenancy` — ห้าม `select(Patient)` ตรง ๆ ใน `care_*`
  (เดิมเขียนว่า helper ของ `ap_tenancy` · โมดูลนั้นถูกลบเมื่อ tenancy ขึ้น kernel — ADR-0003 รอบที่ 2)
  (มี test บังคับ + review ของทีม A)
- ต้องมีหน้าจัดการ consent ที่ caregiver/ผู้ป่วยเข้าใจได้ ไม่ใช่ config ของ admin เท่านั้น
- รองรับ PDPA ได้ตั้งแต่ต้น: ตอบได้ว่าใครเข้าถึงข้อมูลอะไรเมื่อไร และลบ/ถอนได้จริง
- เพิ่มงานให้ทุกทีมเล็กน้อยในทุก endpoint — ยอมรับ เพราะย้อนกลับมาใส่ทีหลังแพงกว่ามาก

## อัปเดต 2026-08-19 — `consent/v1` เป็น contract ของ platform แล้ว

[agent-platform#15](https://github.com/monthop-gmail/agent-platform/issues/15) ถูกรับเข้าเป็น
[ADR-0012](https://github.com/monthop-gmail/agent-platform/blob/main/decisions/0012-consent-contract.md)
และ publish เป็น `contracts/consent/v1` แล้ว — implementation ของเราปรับตามครบ:

| สิ่งที่ contract บังคับ | ที่เราแก้ |
|---|---|
| **ห้ามมี field `status`** — สถานะต้องคำนวณจาก `revoked_at`/`expires_at` ไม่ใช่เก็บซ้ำ | ลบคอลัมน์ `active` ออก (มันคือ field เก็บสถานะซ้ำที่ contract เตือนไว้ตรง ๆ ว่าจะ drift) |
| การเพิกถอนต้องมี `revoked_by` + `revoked_reason` | `revoke_consent()` บังคับเหตุผท และบันทึกว่าใครถอน |
| `authority_basis` เมื่อผู้ให้ไม่ใช่เจ้าของข้อมูล | **เราบังคับ** (contract ให้เป็น optional) เพราะโดเมนนี้การให้แทนคือกรณีปกติ |

`contracts/consent/v1/` ของเราเหลือเฉพาะ vocabulary ของ scope ซึ่ง platform ระบุว่าเป็นของโดเมน

## หมายเหตุ — เคยพิจารณายก consent ขึ้น kernel แล้ว (2026-08-18)

ทีม pstack เสนอให้ย้าย `ApConsentGrant` ขึ้นเป็นโมดูลของ kernel พร้อม tenancy
([pstack#3](https://github.com/willpower-institute/pstack/issues/3)) — **ตัดสินใจว่าไม่ยกขึ้น kernel**
แล้วส่งไป agent-platform แทน ซึ่งรับเข้าเป็น contract จริงตามที่เห็นด้านบน

1. ADR-0001 กำหนดไว้ว่า domain ที่ยังไม่มีที่อยู่ใน platform ให้ทำที่ repo นี้ก่อน
   แล้วเสนอขึ้นเมื่อมี consumer ตัวที่สองต้องใช้จริง — ตอนนี้มีเราคนเดียว
2. consent เป็น **governance ไม่ใช่ infra** — pstack ตอบว่า "ระบบทำสิ่งนี้ได้ไหม"
   ส่วน consent ตอบว่า "ใครยอมให้ใครเห็นอะไร นานแค่ไหน เพื่ออะไร" ซึ่งอยู่ตระกูลเดียวกับ
   `policy/v1` และ `approval/v1` ของ `agent-platform` ถ้าจะ promote จริง เส้นทางที่ถูกคือ
   **contract ที่ `agent-platform` + implementation ที่ repo ที่ใช้** ไม่ใช่โมดูลใน kernel

ข้อผูกพันที่ตามมา: เก็บ consent ให้ **domain-free** ต่อไป (ใช้ `subject_id` ไม่ใช่ `patient_id`)
เพื่อให้ยกขึ้นทางไหนก็ได้เมื่อถึงเวลา — บังคับด้วยเทสใน `tests/test_architecture_rules.py`

## Sources

[`ref/chatgpt-care-agent-design.md`](../ref/chatgpt-care-agent-design.md) §13, §14 ·
[agent-platform `contracts/identity/v1`](https://github.com/monthop-gmail/agent-platform/blob/main/contracts/identity/v1/identity.schema.yaml) ·
[agent-platform ADR-0007](https://github.com/monthop-gmail/agent-platform/blob/main/decisions/0007-multi-tenancy.md)
