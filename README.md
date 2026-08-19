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

**M1 · M2 เสร็จ · M4 ต่อ LINE แล้ว** — closed loop เดินได้เต็มวง (เตือน → ยืนยัน → เตือนซ้ำ → พลาด →
ส่งต่อผู้ดูแล) พร้อม tenant isolation, consent, policy engine, audit trail, medication
version chain, health journal, นัดหมาย + การเตรียมตัวไปพบหมอ และ orientation/daily brief
ดูรายละเอียดและงานที่ค้างที่ [`architecture/team-plan.md`](architecture/team-plan.md)

## เริ่มต้น

### Docker

```bash
cp .env.example .env      # แก้ PSTACK_SECRET_KEY และ DB_SUPERUSER_PASSWORD ก่อนใช้จริง
docker compose up -d --build
curl localhost:8000/healthz
```

> 🔒 **role ที่แอปใช้ต่อ DB ต้องไม่ใช่ superuser** — image `postgres` สร้าง `POSTGRES_USER`
> เป็น superuser เสมอ และ **RLS ถูก bypass เสมอโดย superuser** (`FORCE ROW LEVEL SECURITY`
> คุมได้แค่ table owner) `DB_SUPERUSER` จึงใช้ bootstrap เท่านั้น ส่วนแอปต่อด้วย `DB_USER`
> ที่ [`deploy/db-init/10-app-role.sh`](deploy/db-init/10-app-role.sh) สร้างเป็น
> `NOSUPERUSER NOBYPASSRLS` · ตรวจได้ด้วย `python conformance/db_role_check.py`

#### ย้าย deployment เดิมมาใช้ role ที่ไม่ใช่ superuser

init script รันเฉพาะตอน `initdb` ครั้งแรก — volume ที่มีข้อมูลอยู่แล้วต้องรันครั้งเดียวด้วยมือ
โดยเชื่อมต่อในฐานะ superuser เดิม (ชื่อเดียวกับ `DB_USER` ของ compose ชุดเก่า):

```sql
BEGIN;
  -- ถอด superuser ออกจาก role ที่แอปใช้อยู่ ไม่ต้องสร้าง role ใหม่และไม่ต้องย้าย ownership
  ALTER ROLE care NOSUPERUSER NOBYPASSRLS;
  -- ต้องมี superuser อีกตัวไว้ดูแลระบบ ไม่งั้นจะไม่เหลือใครแก้ได้
  CREATE ROLE postgres LOGIN PASSWORD 'เปลี่ยนด้วย' SUPERUSER;
COMMIT;
```

แล้วอัปเดต `.env` (`DB_SUPERUSER` / `DB_SUPERUSER_PASSWORD`) ให้ตรง และรัน
`python conformance/db_role_check.py` ยืนยันว่าผ่านก่อนถือว่าเสร็จ

ลองวงจรเต็ม (สร้าง tenant → ผู้ป่วย → กิจวัตร → เตือน → ยืนยัน → ดู audit trail):

```bash
python examples/seed_demo.py
curl -X POST -H "X-Tenant-Id: t-demo-family" localhost:8000/api/care/jobs/tick
```

### ต่อ LINE ให้ผู้ป่วยใช้จริง

1. สร้าง LINE channel ในระบบ — 🔒 **ต้องตั้ง `agent_enabled: false`** ([ADR-0008](decisions/0008-patient-channel-is-deterministic.md))

```bash
curl -X POST localhost:8000/api/line/channels -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name":"Care OA","channel_id":"<LINE channel ID>","channel_secret":"<secret>",
       "access_token":"<long-lived token>","agent_enabled":false,
       "greeting":"สวัสดีครับ พิมพ์ “ผูก <รหัส>” เพื่อเริ่มใช้งานได้เลยครับ"}'
```

2. ตั้ง webhook ที่ LINE Console: `https://<โดเมน>/api/line/webhook/<LINE channel ID>`
3. ออกรหัสจับคู่ให้ผู้ป่วย แล้วให้พิมพ์ `ผูก <รหัส>` ในแชท

```bash
curl -X POST localhost:8000/api/care/line/pairing-codes \
  -H "authorization: Bearer $TOKEN" -H "X-Tenant-Id: t-demo-family" \
  -H 'content-type: application/json' \
  -d '{"patient_id":"<patient_id>","principal_id":"<patient_id>","role":"patient"}'
```

จากนั้นผู้ป่วยพูดกับ OA ได้เลย — “ทำแล้ว” · “ยัง” · “วันนี้วันอะไร” · “พรุ่งนี้ต้องทำอะไร” ·
“วันนี้กินยาอะไร” · “กินยาแล้วยัง” · “จด ...” ส่วนผู้ดูแลผูกด้วย `role: caregiver`
แล้วพิมพ์ “รับเรื่อง” เพื่อหยุดการเตือนเมื่อรับช่วงต่อ

### Dev บนเครื่อง

ต้องมี pstack checkout ไว้ข้าง ๆ (tag เดียวกับ `PSTACK_REF`)

```bash
git clone --branch v0.3.1 https://github.com/willpower-institute/pstack.git ../pstack
python3 -m venv .venv && .venv/bin/pip install -e "../pstack[dev]"

export PSTACK_ADDONS_PATHS=../pstack/addons,care_addons
.venv/bin/uvicorn main:app --reload

.venv/bin/python -m pytest tests/ -q             # เทสบน sqlite (ไม่ต้องมี Postgres)
.venv/bin/python conformance/drift_check.py      # contract ของเรายัง $ref ตรงกับ agent-platform
.venv/bin/python conformance/payload_check.py    # payload จริงที่ระบบผลิต conform contract จริง
.venv/bin/python conformance/migration_check.py  # migration ยังตรงกับ models
.venv/bin/python conformance/rls_check.py        # RLS กันข้าม tenant ได้จริง (Postgres)
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

## ย้าย deployment เดิมเข้า `tenancy` ของ kernel (adopt)

pstack v0.3.0 ย้าย control plane ของ multi-tenancy ขึ้น kernel — deployment ที่มีข้อมูลอยู่แล้ว
ต้อง **rename ตารางเดิมให้ตรงชื่อ canonical ก่อนเปิดโมดูล** แล้ว migration ของ kernel จะข้าม
create ให้เอง ทำใน transaction เดียวเสมอ (rename ล้มกลางคัน = สภาพผสม migration จะ raise เตือน)

```sql
BEGIN;
  DO $$ BEGIN
    IF to_regclass('public.ap_tenant') IS NULL OR to_regclass('public.tenant') IS NOT NULL
    THEN RAISE EXCEPTION 'สภาพไม่พร้อม adopt'; END IF;
  END $$;

  ALTER TABLE ap_tenant        RENAME TO tenant;
  ALTER TABLE ap_workspace     RENAME TO workspace;
  ALTER TABLE ap_tenant_member RENAME TO tenant_member;

  -- ⚠️ Postgres ไม่ rename constraint/index ให้ตอน rename ตาราง — ต้องทำเองทุกตัว
  --    (runbook ของ kernel เขียนว่า PK/FK เปลี่ยนชื่อเอง ซึ่งไม่จริง — ยืนยันบน PG16 แล้ว)
  ALTER TABLE tenant        RENAME CONSTRAINT ap_tenant_pkey                TO tenant_pkey;
  ALTER TABLE workspace     RENAME CONSTRAINT ap_workspace_pkey             TO workspace_pkey;
  ALTER TABLE workspace     RENAME CONSTRAINT ap_workspace_tenant_id_fkey   TO workspace_tenant_id_fkey;
  ALTER TABLE tenant_member RENAME CONSTRAINT ap_tenant_member_pkey         TO tenant_member_pkey;
  ALTER TABLE tenant_member RENAME CONSTRAINT ap_tenant_member_tenant_id_fkey TO tenant_member_tenant_id_fkey;
  ALTER TABLE tenant_member RENAME CONSTRAINT uq_ap_member                  TO uq_tenant_member;

  ALTER INDEX ix_ap_workspace_tenant_id     RENAME TO ix_workspace_tenant_id;
  ALTER INDEX ix_ap_tenant_member_tenant_id RENAME TO ix_tenant_member_tenant_id;
  ALTER INDEX ix_ap_tenant_member_user_id   RENAME TO ix_tenant_member_user_id;
COMMIT;
```

ตรวจว่าชื่อครบก่อนบูต — ต้องได้ 6 constraint และ 3 index ตามชื่อข้างบน:

```sql
SELECT conname FROM pg_constraint
 WHERE conrelid IN ('tenant'::regclass,'workspace'::regclass,'tenant_member'::regclass);
```

`ap_consent_grant` **ไม่ต้อง rename** — โมดูล `ap_consent` adopt ตารางเดิมต่อตามประวัติ

## Conformance กับ agent-platform

repo นี้ประกาศตัวเป็น consumer ผ่าน [`platform-contract.yaml`](platform-contract.yaml)
ตาม [ADR-0006 ของ agent-platform](https://github.com/monthop-gmail/agent-platform/blob/main/decisions/0006-contract-versioning.md)
ซึ่งบังคับครบ 3 ข้อ:

| ข้อกำหนด | ที่นี่ |
|---|---|
| manifest | [`platform-contract.yaml`](platform-contract.yaml) |
| conformance test ที่ validate **payload จริง** | [`conformance/payload_check.py`](conformance/payload_check.py) — รัน scenario จริงหนึ่งวันของผู้ป่วย แล้วเอา audit event ที่ระบบผลิตออกมาไป validate กับ JSON Schema ของ platform ที่ commit ที่ pin ไว้ |
| release gate | ทั้ง drift check และ payload check เป็น step ใน CI ที่รันทุก PR — ไม่ผ่าน = merge ไม่ได้ |

> ต่างกันตรงนี้: `drift_check` ตอบว่า *contract ของเรา* ยังอ้างอิงถูกที่ ·
> `payload_check` ตอบว่า *ระบบของเรา* ทำตาม contract จริง — ข้อหลังคือข้อที่ ADR-0006 นับ

## Tenant isolation — สองด่าน

| ด่าน | คืออะไร | พังแล้วเป็นยังไง |
|---|---|---|
| `scoped()` (app) | ทุก query ที่อ่านข้อมูลของ tenant ต้องผ่าน — เป็นด่านที่ตั้งใจ | ลืมแล้วเห็นข้ามได้ ถ้าไม่มีด่านสอง |
| **RLS (DB)** | policy ของ Postgres กรองตาม GUC `pstack.tenant_id` | ลืมตั้ง scope = **เห็น 0 แถว** (deny by default) |

🔒 **ทุก path ที่เปิด session เองต้อง `core.tenancy.bind_tenant(session, tenant_id)`**
— HTTP ไม่ต้องทำเอง เพราะ `get_scope` ของ kernel ผูกให้แล้ว

`set_tenant()` ตั้ง GUC ที่มีอายุแค่ transaction เดียว ส่วน `bind_tenant()` ผูกไว้กับ session
แล้วตั้งใหม่ให้ทุก transaction — โค้ดที่ commit ระหว่างทางจึงไม่เห็น 0 แถวเงียบ ๆ
(เดิมเราเขียนเองที่ `care_addons/tenant_session.py` แล้วเสนอขึ้น kernel ที่
[pstack#10](https://github.com/willpower-institute/pstack/issues/10) — v0.3.1 รับเข้าแล้วเราจึงลบของเราทิ้ง)

ตารางที่ **ไม่เปิด RLS โดยตั้งใจ**: `care_line_binding` · `care_line_pairing_code` —
เป็น control plane ของช่องทางที่ต้องอ่านให้ได้ก่อนถึงจะรู้ว่า LINE user คนนี้เป็นของ tenant ไหน
(เหตุผลเดียวกับที่ kernel ไม่เปิด RLS บน `tenant`/`tenant_member`)

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
4. [pstack MODULE_GUIDE](https://github.com/willpower-institute/pstack/blob/main/docs/MODULE_GUIDE.md) — วิธีเขียน addon (§9 คือ multi-tenancy/RLS)
5. [agent-platform consumer adoption guide](https://github.com/monthop-gmail/agent-platform/blob/main/architecture/consumer-adoption-guide.md) — ถ้าจะเอา repo อื่นเข้า ecosystem เดียวกัน
6. [`ref/chatgpt-care-agent-design.md`](ref/chatgpt-care-agent-design.md) — ที่มาของทุก requirement

## License

MIT — ดู [LICENSE](LICENSE)
