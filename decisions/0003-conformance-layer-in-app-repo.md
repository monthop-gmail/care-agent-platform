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
2. `depends` ใน manifest อ้างได้เฉพาะ `users` ของ pstack กับ `ap_*` ด้วยกันเอง
3. ทุกชื่อตารางขึ้นต้น `ap_` และทุก public API อยู่ใต้ `/api/platform/...`
4. schema ของ payload ต้อง `$ref` ไปที่ contract ของ `agent-platform` ไม่ใช่นิยามซ้ำ

**หนี้ทางเทคนิคที่ตั้งใจก่อ:** เมื่อ pstack ออก Phase 5 (multi-tenant) ให้ทำ PR
ย้าย `ap_tenancy` ขึ้น kernel แล้วเหลือ shim ในนี้ไว้หนึ่งรอบก่อนลบ — จดไว้เป็น issue ตั้งแต่วันแรก

## Consequences

- ทีม B–E เริ่มงานได้ทันทีโดยไม่ต้องรอ pstack
- `care_*` ทุกตัวต้องมี `depends: ["ap_tenancy", "ap_audit", "ap_policy"]` เป็นอย่างน้อย — ไม่มีข้อยกเว้น
- มีความเสี่ยงว่า `ap_*` จะโตจนกลายเป็น kernel คู่ขนาน → คุมด้วยกฎ 4 ข้อข้างบน + review ของทีม A
- ถ้าวันหนึ่ง pstack ไม่รับ `ap_tenancy` ขึ้น kernel ก็ยังไม่พัง — มันทำงานเป็น addon ได้ตลอดไป
