# ADR-0001: care-agent-platform เป็น consumer ของ agent-platform

**Status:** Accepted (2026-08-18)
**Date:** 2026-08-18

## Context

`agent-platform` วาง identity / gateway / runtime / workflow / policy / capability / contracts
ไว้เป็น platform layer แบบ tech-neutral และ
[ADR-0008 ของ repo นั้น](https://github.com/monthop-gmail/agent-platform/blob/main/decisions/0008-reference-stack.md)
ห้ามมี `pyproject.toml` / `Dockerfile` / typed SDK ใน repo — implementation เป็นหน้าที่ repo ลูก

โจทย์ที่เรากำลังทำคือ **ดูแลผู้ป่วยที่เริ่มมีภาวะความจำเสื่อม** (ที่มา:
[`ref/chatgpt-care-agent-design.md`](../ref/chatgpt-care-agent-design.md)) ซึ่งมี domain logic
เฉพาะทางเยอะมาก — ยา นัดหมอ การเตรียมตัว กิจวัตร ความจำ ของใช้ในบ้าน

ถ้าเอา logic เหล่านี้ยัดเข้า `agent-platform` core จะทำให้ platform ผูกกับ healthcare
และ consumer ตัวถัดไป (security / agriculture / education) ต้องแบกของที่ไม่ใช้

## Decision

`care-agent-platform` เป็น **consumer** — ไม่ใช่ส่วนขยายของ core

```
agent-platform          contracts เท่านั้น · tech-neutral · ห้ามมี healthcare logic
      │ conform
care-agent-platform     healthcare / elder-care domain implementation  ← repo นี้
```

**สิ่งที่ repo นี้ทำได้:**

- นิยาม contract ของ **โดเมนตัวเอง** ใน `contracts/` (patient, medication, appointment, …)
- อ้าง `$defs` ของ `agent-platform` ผ่าน `$ref` — ห้ามนิยาม `TenantId` / `Principal` / `ActionRisk` ซ้ำเอง
- เพิ่ม event type ใหม่แบบ additive (ดู [ADR-0004](0004-care-event-vocabulary.md))

**สิ่งที่ repo นี้ทำไม่ได้:**

- แก้ความหมายของ contract ใน `agent-platform` — ต้องไปเปิด ADR ที่ repo นั้น
- ลดทอน guarantee ของ `event/v1` (append-only · no silent state change · reject event ที่ resolve tenant ไม่ได้)
- ตั้งชื่อ id ใหม่ที่ทับซ้อนกับ `identity/v1`

## Consequences

- `conformance/drift_check.py` ต้องตรวจว่า contract ของเรายัง `$ref` ตรงกับ `agent-platform` เวอร์ชันที่ pin ไว้ และ CI ต้อง fail เมื่อ drift
- เวลา platform ออก contract version ใหม่ เราอัปเกรดเป็นรอบ ๆ ใน PR เดียว ไม่ใช่ทีละไฟล์
- domain ที่ยังไม่มีที่อยู่ใน platform (เช่น `consent`) ให้ทำที่นี่ก่อน แล้วเสนอขึ้น platform เมื่อมี consumer ตัวที่สองต้องใช้

## Sources

[`ref/chatgpt-care-agent-design.md`](../ref/chatgpt-care-agent-design.md) §2, §24 ·
[agent-platform ADR-0001](https://github.com/monthop-gmail/agent-platform/blob/main/decisions/0001-platform-scope.md) ·
[agent-platform ADR-0008](https://github.com/monthop-gmail/agent-platform/blob/main/decisions/0008-reference-stack.md)
