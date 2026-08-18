# care-agent-platform

**AI External Memory & Care Companion** — ผู้ช่วยความจำและการดูแลสำหรับผู้ป่วยที่เริ่มมีภาวะความจำเสื่อม
ผู้สูงอายุ และผู้ที่ต้องการความช่วยเหลือด้านกิจวัตรประจำวัน

ระบบนี้ **ไม่ใช่หมอ และไม่ใช่ผู้มีอำนาจตัดสินใจทางการแพทย์** — เป็นชั้นของการจำ เตือน บันทึก
เตรียมตัว และส่งต่อให้คน โดยมีผู้ดูแลและบุคลากรทางการแพทย์เป็น authority เสมอ

```
                 PATIENT
                    │
              CARE AGENT
                    │
   ┌────────────────┼────────────────┐
   ▼                ▼                ▼
Remember         Prepare          Observe
   └────────────────┼────────────────┘
                    ▼
                 Assist
                    │  ทำไม่ได้?
                    ▼
                Caregiver
                    │  เรื่องทางคลินิก?
                    ▼
                  Doctor
```

## ตำแหน่งในระบบนิเวศ

```
agent-platform        contracts · tech-neutral · ไม่มีโค้ด
      │ conform ([ADR-0001])
care-agent-platform   healthcare / elder-care domain  ← repo นี้
      │ PSTACK_REF (pin tag · [ADR-0002])
   pstack             FastAPI kernel · modules · LINE · MCP · jobs
```

repo นี้เก็บเฉพาะ **addons ของตัวเอง** (`care_addons/`) — ไม่มีโค้ด pstack อยู่ในนี้

## สถานะ

**M1 เสร็จ · M2 เสร็จ** — closed loop เดินได้เต็มวง (เตือน → ยืนยัน → เตือนซ้ำ → พลาด →
ส่งต่อผู้ดูแล) พร้อม tenant isolation, consent, policy engine, audit trail, medication
version chain, health journal, นัดหมาย + การเตรียมตัวไปพบหมอ และ orientation/daily brief
ดูรายละเอียดและงานที่ค้างที่ [`architecture/team-plan.md`](architecture/team-plan.md)

## เริ่มต้น

### Docker

```bash
cp .env.example .env      # แก้ PSTACK_SECRET_KEY ก่อนใช้จริง (และ APP_PORT ถ้าพอร์ตชน)
docker compose up -d --build
curl localhost:8000/healthz
```

ลองวงจรเต็ม (สร้าง tenant → ผู้ป่วย → กิจวัตร → เตือน → ยืนยัน → ดู audit trail):

```bash
python examples/seed_demo.py
curl -X POST -H "X-Tenant-Id: t-demo-family" localhost:8000/api/care/jobs/tick
```

### Dev บนเครื่อง

ต้องมี pstack checkout ไว้ข้าง ๆ (tag เดียวกับ `PSTACK_REF`)

```bash
git clone --branch v0.2.0 https://github.com/willpower-institute/pstack.git ../pstack
python3 -m venv .venv && .venv/bin/pip install -e "../pstack[dev]"

export PSTACK_ADDONS_PATHS=../pstack/addons,care_addons
.venv/bin/uvicorn main:app --reload

.venv/bin/python -m pytest tests/ -q             # เทสบน sqlite (ไม่ต้องมี Postgres)
.venv/bin/python conformance/drift_check.py      # contract ยังตรงกับ agent-platform
.venv/bin/python conformance/migration_check.py  # migration ยังตรงกับ models
```

เทสบน Postgres แบบเดียวกับ CI และ production:

```bash
docker run -d --name pg-test -e POSTGRES_USER=care -e POSTGRES_PASSWORD=care \
  -e POSTGRES_DB=care_test -p 55432:5432 postgres:16-alpine

PSTACK_DATABASE_URL="postgresql+asyncpg://care:care@localhost:55432/care_test" \
  .venv/bin/python -m pytest tests/ -q
```

**แก้ `models.py` = ต้องมี migration เสมอ** (CI ตรวจให้ ไม่ผ่านแล้ว merge ไม่ได้):

```bash
.venv/bin/python ../pstack/cli.py makemigration care_medication -m "add version chain"
```

แต่ละโมดูลมี lineage และ version table ของตัวเอง (`alembic_version_<module>`) ไม่ชนกัน
— ทีมที่แก้คนละโมดูลจึงสร้าง migration พร้อมกันได้โดยไม่ต้องรอกัน

## โครงสร้าง

```
architecture/   ภาพรวม · แผนทีม · risk model · patient lifecycle
decisions/      ADR — อ่านก่อนแตะโค้ด
contracts/      YAML schema ของโดเมนนี้ ($ref ไปที่ agent-platform)
policies/       authority map และ escalation policy (config ไม่ hard-code)
care_addons/    โค้ดทั้งหมด — หนึ่ง addon = หนึ่งเจ้าของ = merge แยกกันได้
conformance/    drift check เทียบกับ contract ของ agent-platform
tests/          scenario tests (สำคัญกว่า unit test ในโปรเจกต์นี้)
ref/            บทสนทนา/blueprint ต้นทาง — เก็บไว้ให้ทุกทีมอ้างอิงร่วมกัน
```

## หลักการที่บังคับใช้ในโค้ด ไม่ใช่แค่เขียนไว้

1. **AI ≠ Doctor** — ไม่วินิจฉัย ไม่สั่งการรักษา
2. **AI ≠ Authority** — action ที่แตะโลกจริงต้องผ่าน `ap_policy` ทุกครั้ง ([ADR-0006](decisions/0006-ai-has-no-medical-authority.md))
3. **Observation ≠ Diagnosis** — schema ห้ามมี field ที่แปลผลทางการแพทย์ ([ADR-0004](decisions/0004-care-event-vocabulary.md))
4. **Personal Memory ≠ Medical Truth** — ทุกข้อมูลสำคัญมี `source` + `version` ([ADR-0005](decisions/0005-medication-versioning.md))
5. **High-risk ต้องมี governance** — ยาเป็น `human_command_required` เสมอ แก้ config ให้หลวมกว่านี้ไม่ได้
6. **ทุก action ต้อง audit ได้** — append-only ตอบได้ว่า "ทำไม agent ถึงส่งข้อความนี้"
7. **Data ต้อง tenant/consent aware** — RBAC อย่างเดียวไม่พอ ([ADR-0007](decisions/0007-consent-and-data-access.md))

## สำหรับทีมที่เพิ่งเข้ามา

อ่านตามลำดับนี้:

1. [`architecture/care-agent-architecture.md`](architecture/care-agent-architecture.md) — ระบบนี้คืออะไร
2. [`architecture/team-plan.md`](architecture/team-plan.md) — ทีมคุณทำ addon ไหน milestone ไหน
3. [`decisions/`](decisions/) — ข้อผูกพันที่แก้ไม่ได้เอง
4. [pstack MODULE_GUIDE](https://github.com/willpower-institute/pstack/blob/main/docs/MODULE_GUIDE.md) — วิธีเขียน addon
5. [`ref/chatgpt-care-agent-design.md`](ref/chatgpt-care-agent-design.md) — ที่มาของทุก requirement

## License

MIT — ดู [LICENSE](LICENSE)
