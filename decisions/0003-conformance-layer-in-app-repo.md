# ADR-0003: platform conformance layer (`ap_*`) อยู่ใน repo นี้ก่อน

**Status:** Accepted (2026-08-18)
**Depends on:** [ADR-0001](0001-consumer-of-agent-platform.md), [ADR-0002](0002-runtime-on-pstack.md)

## Context

`agent-platform` บังคับสามอย่างที่ **pstack v0.1.0 ยังไม่มี**:

| ต้องมีตาม contract | pstack v0.1.0 |
|---|---|
| `identity/v1` — `Tenant → Workspace → Resource`, isolation ลงถึง DB/index/storage (ADR-0007 ของ platform) | ไม่มีเลย — `grep -i 'tenant\|workspace\|organization'` ทั้ง repo = 0 hit · Roadmap Phase 5 ยังไม่ทำ |
| `event/v1` — append-only audit log มี `event_id / tenant_id / subject / actor / policy_result / correlation_id` + guarantee "no silent state change" | มีแต่ event bus แบบ pub/sub (fire-and-forget) ไม่ persist ไม่มี envelope |
| `policy/v1` + ADR-0010 — `action_risk × authority_map → authority` (`auto / notify / approval_required / human_command_required`) | มีแต่ permission string ใน RBAC — ไม่มีแนวคิด risk หรือ authority |

สามอย่างนี้เป็น **เงื่อนไขเปิดงาน** ของทุกทีม: `care_medication` เขียน audit ไม่ได้ถ้าไม่มี audit,
`care_escalation` ตัดสินไม่ได้ถ้าไม่มี policy, และไม่มี addon ไหนเก็บข้อมูลผู้ป่วยได้อย่างปลอดภัยถ้าไม่มี tenancy

ถ้ารอ pstack ทำ Phase 5 ให้เสร็จก่อน ทีม B–E จะว่างงานทั้งรอบ
ถ้าทำในนี้แบบไม่วางแผน ก็จะกลายเป็น kernel เงาที่ไม่มีวันกลับขึ้น upstream

## Decision

ทำเป็น **addons ที่ขึ้นต้นด้วย `ap_`** ใน repo นี้ก่อน โดยตั้งใจให้ promote ขึ้น pstack ทีหลัง

```
care_addons/
├── ap_tenancy/     Tenant / Workspace + tenant-scoped session guard
├── ap_audit/       append-only audit event store ตาม event/v1
├── ap_policy/      action_risk × authority_map → authority (config ไม่ hard-code)
└── ap_approval/    (M3) human approval สำหรับ authority=approval_required
```

**กติกาที่ทำให้ promote ได้จริง — ทุก PR ที่แตะ `ap_*` ต้องผ่านทั้ง 4 ข้อ:**

1. **ห้าม import อะไรจาก `care_*`** — `ap_*` ต้องไม่รู้จักคำว่า patient / medication / caregiver เลย
   (มี test บังคับข้อนี้ที่ `tests/test_ap_layer_is_domain_free.py`)
2. `depends` ใน manifest อ้างได้เฉพาะ **โมดูลของ kernel** (`users` · `tenancy`) กับ `ap_*` ด้วยกันเอง
   — เจตนาคือห้ามพึ่งโดเมน ไม่ใช่ห้ามพึ่ง kernel · เดิมเขียนว่า "`users` เท่านั้น" ตอนที่ kernel
   ยังไม่มี `tenancy` (แก้ 2026-08-19 หลัง pstack v0.3.0)
3. ทุกชื่อตารางขึ้นต้น `ap_` และทุก public API อยู่ใต้ `/api/platform/...`
4. schema ของ payload ต้อง `$ref` ไปที่ contract ของ `agent-platform` ไม่ใช่นิยามซ้ำ

## อัปเดต 2026-08-19 — `tenancy` ขึ้น kernel แล้ว รอบที่ 1

pstack ออก [PR#9](https://github.com/willpower-institute/pstack/pull/9) (v0.3.0 draft) ตามที่เราเสนอ
ฝั่งเรา adopt ตามนี้:

| ของเดิมใน `ap_tenancy` | ปลายทาง |
|---|---|
| `ApTenant` · `ApWorkspace` · `ApTenantMember` + `TenantScope`/`scoped`/`assert_same_tenant`/`get_scope` | kernel `tenancy` + `core.tenancy` |
| `clock.py` | kernel `core.clock` |
| `ids.py` | kernel `core.tenancy` (`ID_PATTERN` ตรงกับ `identity/v1` — มีเทสล็อกไว้ที่ `tests/test_kernel_contract_lock.py`) |
| `ApConsentGrant` + service + endpoint | **โมดูลใหม่ `ap_consent`** — consent เป็น governance ไม่ใช่ infra |

`ap_tenancy` เหลือเป็น **shim ที่ re-export อย่างเดียว** ตามที่ ADR นี้เขียนไว้ว่าจะทำ shim หนึ่งรอบ
ก่อนลบ — รอบที่ 2 จะย้าย import ทั้ง 111 จุดแล้วลบโมดูลนี้ทิ้ง

**หนี้ที่รู้ตัวแล้ว:** `ap_audit` มีคอลัมน์ชื่อ `care_event_type` ซึ่งเป็นคำของโดเมน
(เทสตรวจเฉพาะคำว่า patient/medication/caregiver จึงไม่จับ) ตอน promote ขึ้น kernel
ต้องเปลี่ยนเป็นชื่อกลางเช่น `domain_event_type` พร้อม migration — ยังไม่ทำตอนนี้เพราะ
กระทบ call site จำนวนมากโดยไม่ได้ประโยชน์เพิ่มก่อนถึงวัน promote

**กฎที่บังคับไม่ได้ใน `ap_*`:** ข้อกำหนดของโดเมนอย่าง "care event ทุกตัวต้องมี `patient_id`"
เอาไปใส่ใน `ap_audit` ไม่ได้ (จะผิดกฎข้อ 1 ทันที) — บังคับที่ `conformance/payload_check.py`
ซึ่ง validate payload จริงกับ `contracts/event/v1/care-event.schema.yaml` ใน CI แทน

**หนี้ทางเทคนิคที่ตั้งใจก่อ:** เมื่อ pstack ออก Phase 5 (multi-tenant) ให้ทำ PR
ย้าย `ap_tenancy` ขึ้น kernel แล้วเหลือ shim ในนี้ไว้หนึ่งรอบก่อนลบ — จดไว้เป็น issue ตั้งแต่วันแรก

## อัปเดต 2026-08-19 — รอบที่ 2 จบแล้ว: `ap_tenancy` ถูกลบ

ย้าย import ทั้งหมด (53 ไฟล์) ไปที่ต้นทางจริงแล้วลบโมดูล shim ทิ้ง:

| import เดิม | ปลายทาง |
|---|---|
| `care_addons.ap_tenancy.clock` | `core.clock` |
| `care_addons.ap_tenancy.ids` | `core.tenancy` |
| `care_addons.ap_tenancy.deps` | `addons.tenancy.deps` |
| `care_addons.ap_tenancy.services` (tenant primitives) | `core.tenancy` |
| `care_addons.ap_tenancy.services` (tenant/member CRUD) | `addons.tenancy.services` |
| `care_addons.ap_tenancy.services` (consent) | `care_addons.ap_consent.services` |

- `depends` ของทุก `care_*` เปลี่ยนจาก `ap_tenancy` เป็น `tenancy` ของ kernel
  (`tests/test_architecture_rules.py` บังคับข้อนี้อยู่)
- endpoint `/api/platform/tenants` ที่ deprecated ไว้หนึ่งรอบถูกลบ — ใช้ `/api/tenancy/tenants`
  ของ kernel แทน (permission เปลี่ยนจาก `platform.tenancy.manage` เป็น `tenancy.manage`)
- deployment ที่เคยติดตั้ง `ap_tenancy` มีตาราง `alembic_version_ap_tenancy` ค้างอยู่
  ไม่มีผลกับการทำงาน แต่กวาดทิ้งได้ด้วย `DROP TABLE alembic_version_ap_tenancy;`
  (ดูขั้นตอนใน README §adopt)

**สิ่งที่ไม่เปลี่ยน:** กฎ 4 ข้อของ `ap_*` ยังอยู่ครบ และ `ap_consent` · `ap_audit` · `ap_policy` ·
`ap_approval` ยังเป็นชั้น conformance ที่ `care_*` ทุกตัวต้องผ่าน

## Consequences

- ทีม B–E เริ่มงานได้ทันทีโดยไม่ต้องรอ pstack
- `care_*` ทุกตัวต้องมี `depends: ["tenancy", "ap_audit", "ap_policy"]` เป็นอย่างน้อย — ไม่มีข้อยกเว้น
  (เดิมคือ `ap_tenancy` · เปลี่ยนเมื่อ tenancy ขึ้น kernel — ดูอัปเดตรอบที่ 2 ข้างบน)
- มีความเสี่ยงว่า `ap_*` จะโตจนกลายเป็น kernel คู่ขนาน → คุมด้วยกฎ 4 ข้อข้างบน + review ของทีม A
- ถ้าวันหนึ่ง pstack ไม่รับ `ap_tenancy` ขึ้น kernel ก็ยังไม่พัง — มันทำงานเป็น addon ได้ตลอดไป
