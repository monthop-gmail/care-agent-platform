# ADR-0002: runtime อยู่บน pstack แบบ app repo (pin tag)

**Status:** Accepted (2026-08-18)
**Depends on:** [ADR-0001](0001-consumer-of-agent-platform.md)

## Context

`agent-platform` ไม่บังคับ stack ให้ repo ลูก แต่กำหนดว่า repo ลูกต้อง `docker compose up` ได้
เราจึงต้องเลือก runtime เอง

[`pstack`](https://github.com/willpower-institute/pstack) เป็น modular BaaS บน FastAPI
(SQLAlchemy 2.0 async · Postgres · Redis · ARQ · Alembic ต่อโมดูล) ที่ทีมเดียวกันดูแลอยู่แล้ว
และมีของที่ blueprint ต้องการอยู่ครบหลายอย่าง:

| blueprint ต้องการ | pstack v0.1.0 |
|---|---|
| patient interface บน LINE | `line_oa` — multi-channel, verify signature, LIFF, account linking, agent bridge |
| closed-loop reminder + retry + timeout | ARQ background jobs + worker แยกโปรเซส |
| agent ห้ามแตะ backend ตรง ต้องผ่าน tool layer | `@agent_tool` registry (RBAC-scoped) + `mcp_server` |
| 1 agent = 1 module | Odoo-style addons + Alembic ต่อโมดูล (`alembic_version_<module>` ไม่ชนกัน) |
| หลายทีมทำงานขนานกัน | `pstack-app-template` — app repo เก็บเฉพาะ addons แล้ว pin `PSTACK_REF` |

## Options

### A. app repo pin tag ตาม `pstack-app-template` (เลือก)

repo นี้เก็บเฉพาะ `care_addons/` แล้ว pin `PSTACK_REF` — Dockerfile/CI clone pstack ตาม tag

- ✅ pstack ได้ fix/feature จาก app ตัวอื่น (`pstack-vdo`, `pstack-vituntasa`) มาใช้ฟรี
- ✅ ขอบเขตชัด: kernel เปลี่ยน = PR ที่ pstack + tag ใหม่ ไม่ใช่แก้ในนี้
- ❌ ต้องรอ tag เมื่ออยากได้ของจาก kernel → แก้ด้วย [ADR-0003](0003-conformance-layer-in-app-repo.md)

### B. vendor pstack เข้ามาใน repo

- ✅ แก้อะไรก็ได้ทันที
- ❌ 2 repo แตกสาย · fix ที่ทำที่นี่ไม่กลับไปหา app ตัวอื่น · merge upstream แพงขึ้นทุกเดือน

### C. เขียน FastAPI ใหม่ ไม่ใช้ pstack

- ✅ ควบคุม architecture ได้เต็มที่ตั้งแต่แรก
- ❌ ทิ้ง `line_oa` / `ai_agent` / `mcp_server` / jobs / loader ที่ทำเสร็จและมีคนใช้จริงแล้ว
- ❌ ทีมต้องดูแล kernel เองอีกหนึ่งชุดโดยไม่ได้ประโยชน์เพิ่ม

## Decision

**A** — `care-agent-platform` เป็น pstack app repo, pin `PSTACK_REF` ใน `.env.example`

**กติกา:**

- **ห้ามแก้โค้ด pstack ใน repo นี้** อยากได้อะไรจาก kernel → PR ที่ pstack แล้วออก tag ใหม่
- อัปเกรด `PSTACK_REF` เป็นรอบ ๆ ใน PR เดียว อ่าน CHANGELOG ของ pstack ก่อนเสมอ
- addons path ของ repo นี้ชื่อ `care_addons` (ห้ามชื่อ `addons` เพราะชนกับของ pstack)

## Consequences

- ~~**pstack ต้องมี LICENSE ก่อน repo นี้ public**~~ ✅ **จัดการแล้ว 2026-08-18** —
  ตอนตัดสินใจ pstack ยังไม่มีไฟล์ LICENSE ซึ่งตามกฎหมายลิขสิทธิ์แปลว่า all rights reserved
  ตอนนี้ pstack เป็น MIT แล้วและออก
  [`v0.1.1`](https://github.com/willpower-institute/pstack/releases/tag/v0.1.1) เป็น tag แรกที่มีสัญญาอนุญาต
  — repo นี้ pin tag นั้น
- ทุก addon ในนี้ต้องเขียนตาม MODULE_GUIDE ของ pstack (manifest เป็น dict literal, `router: APIRouter`, hooks, migrations ต่อโมดูล)
- test รันบน sqlite ได้โดยไม่ต้องมี Postgres — เก็บ compatibility นี้ไว้ ไม่ใช้ฟีเจอร์เฉพาะ Postgres โดยไม่มี fallback

## Sources

[pstack README](https://github.com/willpower-institute/pstack) · [pstack CHANGELOG v0.1.0](https://github.com/willpower-institute/pstack/blob/main/CHANGELOG.md) ·
[pstack-app-template](https://github.com/willpower-institute/pstack-app-template) ·
[`ref/chatgpt-care-agent-design.md`](../ref/chatgpt-care-agent-design.md) §20
