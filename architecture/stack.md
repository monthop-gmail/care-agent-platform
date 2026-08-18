# Stack

| ส่วน | ใช้ | มาจากไหน |
|---|---|---|
| Runtime / kernel | [pstack](https://github.com/willpower-institute/pstack) `v0.2.0` (MIT) pin tag | [ADR-0002](../decisions/0002-runtime-on-pstack.md) |
| Web | FastAPI + Pydantic v2 | pstack |
| ORM | SQLAlchemy 2.0 (async) + Alembic ต่อโมดูล | pstack |
| Database | PostgreSQL (test รันบน sqlite ได้) | pstack |
| Cache / event broadcast | Redis | pstack |
| Background jobs | ARQ (worker แยกโปรเซส) | pstack |
| LLM | Anthropic SDK — Claude (`claude-opus-5`) | pstack `ai_agent` |
| Tool boundary | `@agent_tool` registry + `mcp_server` (MCP Streamable HTTP) | pstack |
| Patient channel | LINE OA (`line_oa`) + LIFF | pstack |
| Contract | YAML / JSON Schema `$ref` ไปที่ agent-platform | [ADR-0001](../decisions/0001-consumer-of-agent-platform.md) |

## ทำไมไม่เขียน FastAPI ใหม่เอง

pstack ทำของที่เราต้องการเสร็จแล้วและมีคนใช้จริง (`pstack-vdo`, `pstack-vituntasa`) —
`line_oa` ตัวเดียวประหยัดงานหลายสัปดาห์ และ module loader + Alembic ต่อโมดูล
คือสิ่งที่ทำให้ **หลายทีม merge ขนานกันได้โดยไม่ชน migration กัน** ซึ่งเป็นข้อจำกัดหลักของโปรเจกต์นี้

## ทำไมไม่แก้ pstack ตรง ๆ

เพราะ app repo ตัวอื่นใช้ kernel เดียวกันอยู่ การแก้ในนี้จะทำให้ fix ไม่กลับไปหาใคร
ของที่ kernel ยังไม่มี (tenancy/audit/policy) ทำเป็น `ap_*` addon ก่อน แล้ว promote ขึ้นทีหลัง
([ADR-0003](../decisions/0003-conformance-layer-in-app-repo.md))

## เวอร์ชันที่ pin

`PSTACK_REF` อยู่ใน `.env.example` — Dockerfile และ CI อ่านค่าจากที่เดียวกัน
อัปเกรดเป็น PR แยกเสมอ และอ่าน [CHANGELOG ของ pstack](https://github.com/willpower-institute/pstack/blob/main/CHANGELOG.md) ก่อน

## ข้อจำกัดที่ต้องรักษา

- **test ต้องรันบน sqlite ได้โดยไม่ต้องมี Postgres** — ห้ามใช้ฟีเจอร์เฉพาะ Postgres โดยไม่มี fallback
  · แต่ CI รันทั้ง sqlite และ Postgres เสมอ (matrix) เพราะ sqlite อย่างเดียวไม่พอ
- **แก้ `models.py` = ต้องมี Alembic migration** — `conformance/migration_check.py` บังคับใน CI
- **`docker compose up` ต้องขึ้นได้เสมอบน main** — เป็น DoD ที่ `agent-platform` กำหนดให้ repo ลูก
- addons path ของ repo นี้ชื่อ `care_addons` ห้ามชื่อ `addons` (ชนกับ pstack)
