# Team Plan

เอกสารนี้คือสิ่งที่ทุกทีมใช้ร่วมกัน — **อ่านก่อนเปิด branch แรก**

## หน่วยของงานคือ addon

หนึ่ง addon = หนึ่งเจ้าของ = merge แยกกันได้ = migration ของตัวเอง (`alembic_version_<module>`)
ทีมไม่ต้องรอกันที่ระดับไฟล์ ต้องรอกันแค่ที่ระดับ **contract** เท่านั้น

```
care_addons/
├── ap_consent/       ทีม A   ความยินยอมเข้าถึงข้อมูลของบุคคล (consent/v1)
│                          (tenant/workspace/scope ขึ้น kernel แล้ว — `tenancy` ของ pstack)
├── ap_audit/         ทีม A   append-only audit event store (event/v1)
├── ap_policy/        ทีม A   action_risk × authority_map → authority
├── ap_approval/      ทีม A   human approval (M3)
│
├── care_patient/     ทีม B   patient, caregiver, care profile (feature flags)
├── care_routine/     ทีม B   กิจวัตร + มื้ออาหาร + closed-loop reminder
├── care_medication/  ทีม B   version chain, meal relation, prescriber, conflict
├── care_appointment/ ทีม B   นัดหมาย + reminder ล่วงหน้า
│
├── care_journal/     ทีม C   อาการ/เหตุการณ์/คำถามถึงหมอ + visit brief
├── care_careplan/    ทีม C   คำสั่งหลังพบหมอ → task ต่อเนื่อง (เดิน/ดื่มน้ำ/ยานวด)
├── care_orientation/ ทีม C   วันนี้วันอะไร/อยู่ไหน/ต้องทำอะไร + daily brief
│
├── care_activity/    ทีม D   task continuity หลายขั้นตอน (ซักผ้า ทำอาหาร)
├── care_inventory/   ทีม D   ของกิน/ของใช้ + วันหมดอายุ + กันซื้อซ้ำ
├── care_home/        ทีม D   เสื้อผ้า/ของใช้ประจำตัว (cognitive offloading)
├── care_safety/      ทีม D   sensor/IoT/GPS intake
│
├── care_orchestrator/  A+B   จัดลำดับ event → context → policy → agent → verify
└── care_escalation/    A+B   retry policy, caregiver notification, daily summary
```

ทีม E (Channels & UX) ไม่ได้เป็นเจ้าของ addon แยก แต่ดูแล **ทางเข้า-ออกทั้งหมด**:
LINE adapter (บน `line_oa` ของ pstack), caregiver dashboard, patient UI, daily summary rendering

## ลำดับที่ต้องเดินตาม

```
M0 ── งานเปิดทาง (ทีม A · ก่อนใครเริ่ม)
      ใส่ MIT ที่ pstack + ออก tag → repo นี้ pin ได้ถูกกฎหมาย
      contracts/ + ADR + conformance/drift_check ผ่าน CI
      docker compose up ขึ้นได้พร้อม healthz

M1 ── Foundation (ทีม A)
      ap_tenancy · ap_audit · ap_policy   (ap_tenancy ถูกยกขึ้น kernel แล้วในภายหลัง)
      DoD: tenant isolation มี test พิสูจน์ · ทุก state change มี event · action ที่ไม่ประกาศ risk ถูกปฏิเสธ

M2 ── Care Loop (ทีม B ขนานกับ ทีม C)
      B: care_patient → care_routine → care_medication → care_appointment
      C: care_journal → care_orientation (ทั้งคู่พึ่งแค่ ap_* ทำขนานได้ทันที)
      DoD: reminder → ack → missed → escalate ครบวง มี scenario test

M3 ── Escalation & Prep (A+B+C)
      ✅ ap_approval · care_orchestrator · care_escalation · care_appt_prep · care_careplan
      DoD: ✅ daily summary ส่งได้ · ✅ approval ค้างได้ตลอดกาลโดยไม่มี auto-approve

M4 ── Intelligence & Channels (C+E)
      ✅ LINE ของผู้ป่วย/ผู้ดูแล (care_line)
      ⬜ personal memory/RAG · caregiver dashboard · LIFF
      DoD: ถามอะไรที่ไม่มีหลักฐาน ต้องตอบว่าไม่มีข้อมูล (มี adversarial test) — ผ่านแล้วสำหรับ LINE

M5 ── Daily Living & Safety (D)
      ✅ care_activity · care_inventory · care_home · care_safety (ทางเข้าของ IoT/wearable)
      DoD: ✅ เครื่องเสร็จ ≠ งานเสร็จ · ✅ เตือนว่ามีอยู่แล้วโดยไม่ห้ามซื้อ
           ✅ ไม่แน่ใจ = unknown ไม่ใช่การเดา · ✅ สัญญาณที่ไม่มั่นใจไม่ปลุกคน

M6 ── Multi-organization (A+E)
      clinic/hospital/pharmacy connector · care plan ข้ามองค์กร · compliance hardening
```

**เส้นทางวิกฤต:** M0 → M1 เท่านั้น ทุกทีมที่เหลือขนานกันได้หลัง M1 เพราะพึ่ง `ap_*` เหมือนกันหมด

## สถานะปัจจุบัน (2026-08-19)

**เดินได้แล้ว** — `docker compose up` ขึ้น, `pytest` 118 เทสผ่านทั้ง sqlite และ Postgres,
conformance ครบ 5 ตัว (drift · payload · migration · db_role · rls)

| addon | สถานะ |
|---|---|
| `ap_consent` | ✅ consent 5 มิติ + เพิกถอน + `as_consent_grant` ตาม `consent/v1` |
| ~~`ap_tenancy`~~ | ✅ ยกขึ้น kernel ครบแล้ว — โมดูลถูกลบ ใช้ `tenancy`/`core.tenancy`/`core.clock` ตรง ๆ |
| `ap_audit` | ✅ append-only store + intake validation + `/trail/{correlation_id}` |
| `ap_policy` | ✅ authority_map + floor + `@care_action` + catalog endpoint |
| `care_patient` | ✅ patient/caregiver/care team/care profile |
| `care_escalation` | ✅ closed loop เต็มวง: remind → backoff → ask → missed → escalate + quiet hours + aggregation |
| `care_routine` | ✅ routine/มื้ออาหาร → materialize เป็น job (idempotent) + แผนวันนี้ |
| `care_medication` | ✅ version chain, meal relation, prescriber, conflict detection, reconciliation summary |
| `care_journal` | ✅ อาการ/คำถามถึงหมอ + visit brief |
| `care_appointment` | ✅ นัดหมาย + reminder ล่วงหน้า + **preparation checklist** + visit brief + บันทึกผลหลังพบหมอ |
| `care_orientation` | ✅ 5 ชั้น (เวลา/วันที่/สถานที่/คน/แผน) + daily brief + temporal memory ("พรุ่งนี้") |
| `care_line` | ✅ ช่องทางจริงของผู้ป่วย — จับคู่บัญชี, ส่ง reminder ออก LINE, รับคำตอบกลับแบบ deterministic ([ADR-0008](../decisions/0008-patient-channel-is-deterministic.md)) |
| `ap_approval` | ✅ คิวรออนุมัติตาม `approval/v1` — decision immutable, ไม่มี auto-approve, ผู้ยื่นตัดสินเองไม่ได้ ([ADR-0009](../decisions/0009-approval-waits-forever.md)) |
| `care_orchestrator` | ✅ รอบวัน — สร้างงานประจำวันให้ทุกคนเอง + สรุปประจำวันตามเวลาท้องถิ่นของผู้ป่วย + ปิดคำขอที่เลยกำหนด |
| `care_careplan` | ✅ คำสั่งหลังพบหมอ → งานที่เกิดซ้ำจริง — จดได้แค่ proposed ต้องมีคนยืนยัน · adherence ไม่มีบันทึกตอบว่า "ข้อมูลไม่พอ" ไม่ใช่ 0% |
| `care_activity` | ✅ งานหลายขั้นตอน — เครื่องซักเสร็จ ≠ งานเสร็จ · ขั้นที่ค้างเกินเวลาเรียกผู้ดูแลเอง |
| `care_inventory` | ✅ ของที่บ้าน + วันหมดอายุ — เตือนว่ามีอยู่แล้ว **ไม่ห้ามซื้อ** · ไม่รู้วันหมดอายุตอบว่าไม่รู้ |
| `care_home` | ✅ ของใช้ประจำตัว/เสื้อผ้า — AI ห้ามเดาสถานะ · "จำไม่ได้" นำไปสู่ workflow ที่ปลอดภัย |
| `care_safety` | ✅ ทางเข้าของ GPS/wearable/sensor — confidence ต่ำไม่ปลุกคน · สัญญาณซ้ำไม่ปลุกซ้ำ · ไม่มีสัญญาณ ≠ ปลอดภัย |

> **หมายเหตุ:** `care_appt_prep` ที่เคยวางไว้แยก ถูกรวมเข้า `care_appointment` แล้ว
> เพราะ `contracts/appointment/v1` นิยาม `PreparationStep` เป็นส่วนหนึ่งของนัดหมาย
> และการแยก addon จะทำให้ต้อง import model ข้ามกันซึ่งผิดกติกาข้อ 4 — **อย่าสร้างซ้ำ**

**งานที่ต้องทำก่อน production (เรียงตามความเร่งด่วน):**

1. ✅ ~~ใส่ LICENSE (MIT) ที่ `willpower-institute/pstack`~~ — เสร็จ 2026-08-18,
   pin `PSTACK_REF=v0.1.1` ซึ่งเป็น tag แรกที่มีสัญญาอนุญาต
2. ✅ ~~Alembic migration ต่อ addon~~ — เสร็จ 2026-08-18, ทุกโมดูลที่มีตารางมี migration
   ของตัวเองแล้ว และ `conformance/migration_check.py` บังคับใน CI ว่าแก้ models แล้วต้องมี revision
3. ✅ ~~ทดสอบบน Postgres จริงใน CI~~ — เสร็จ 2026-08-18, CI เป็น matrix `sqlite` + `postgres`
4. ✅ ~~ผูก `line_oa` เป็นช่องทางจริงของผู้ป่วย~~ — เสร็จ 2026-08-18 ที่ `care_line`
   (M4) · `care_line/services.py` ส่งออกผ่าน `line_client.respond()` จริงแล้ว
5. ✅ ~~ตั้ง ARQ worker ให้เรียก `care_tick` เป็นระยะ~~ — เสร็จ 2026-08-18,
   `care_tick` เป็น `@periodic_job(minute=set(range(60)))` และ service `worker` ใน compose
   รัน `python -m arq core.worker.WorkerSettings` · ตั้งแต่ M3 มี `care_daily_tick`
   (ทุก 15 นาที) เดินรอบวัน: สรุปประจำวัน + ปิดคำขออนุมัติที่เลยกำหนด
6. ✅ ~~adopt `tenancy` ของ kernel~~ — เสร็จ 2026-08-19 (pstack v0.3.1)
   `ap_consent` แยกออกมาเป็นโมดูลของตัวเอง
   · role แอปเป็น `NOSUPERUSER NOBYPASSRLS` · RLS เปิดครบ 15 ตาราง (`conformance/rls_check.py`)
7. ✅ ~~รอบสองของการ adopt~~ — เสร็จ 2026-08-19: ย้าย import 53 ไฟล์ไป `core.tenancy`/`core.clock`/
   `addons.tenancy.*` แล้ว **ลบโมดูล `ap_tenancy` ทิ้ง** · endpoint `/api/platform/tenants` ที่
   deprecated ไว้ก็ถูกลบ ใช้ `/api/tenancy/tenants` ของ kernel แทน (ADR-0003 อัปเดตรอบที่ 2)

## ของที่รอฝั่ง pstack

สิ่งที่ kernel ยังไม่มีและเราแก้เองในรีโปนี้ไม่ได้ (ห้ามแก้โค้ด pstack ที่นี่ — [ADR-0002](../decisions/0002-runtime-on-pstack.md))
ติดตามที่ issue ข้างล่าง **อย่าเปิดรอบใหม่ในนี้ ให้ไปคุยที่ต้นทาง**

| upstream | เรื่อง | สถานะ |
|---|---|---|
| [pstack#2](https://github.com/willpower-institute/pstack/issues/2) | ลงทะเบียน periodic/cron job ไม่ได้ | ✅ **แก้แล้วใน pstack v0.2.0** — `care_tick` เป็น `@periodic_job` แล้ว worker เดินลูปเองทุกนาที |
| [pstack#1](https://github.com/willpower-institute/pstack/issues/1) | loader ไม่สร้างตารางถ้าโมดูลถูก import ก่อน `create_app()` | ✅ **แก้แล้วใน pstack v0.2.0** — ถอด workaround `_ensure_all_tables()` ออกจาก conftest แล้ว |
| [pstack#4](https://github.com/willpower-institute/pstack/issues/4) | worker service ใน compose พังเพราะ `arq` เป็น console script | ✅ **แก้แล้วใน pstack v0.2.1** ทั้ง kernel และ template |
| [pstack#6](https://github.com/willpower-institute/pstack/issues/6) | `line.message.received` ไม่มี `reply_token` | ✅ **v0.2.2** — event พก `reply_token` + มี `client.respond()` (reply ก่อน แล้ว fallback push) · `care_line` ใช้แล้ว ตอบผู้ป่วยไม่กิน push quota |
| [pstack#7](https://github.com/willpower-institute/pstack/issues/7) | `makemigration` ออก revision เปล่าเงียบ ๆ | ✅ **v0.2.1** — ปฏิเสธ + ลบไฟล์เปล่าให้ + บอกวิธีแก้ |
| [pstack#8](https://github.com/willpower-institute/pstack/issues/8) | DX: engine ผูก event loop + accessor ของ periodic job | ✅ **v0.2.1** — `core.testing.isolated_session` + `core.jobs.periodic_jobs()` (เทสเราใช้ public accessor แล้ว) |
| [pstack#3](https://github.com/willpower-institute/pstack/issues/3) | multi-tenancy ใน kernel (Phase 5) | 🟡 ไม่ติด — เคาะแล้ว: RLS + คง `scoped()` · consent คงไว้ที่ repo นี้ ([ADR-0007](../decisions/0007-consent-and-data-access.md)) · kernel ชื่อ `tenancy` (ตัด `ap_`) · **เราลบ `ap_tenancy` เรียบร้อยแล้ว 2026-08-19** |
| [pstack-app-template#1](https://github.com/willpower-institute/pstack-app-template/issues/1) | Dockerfile ของ template copy แค่ addons | ✅ แก้ทั้งสองฝั่งแล้ว |

**กติกา:** เจอข้อจำกัดของ kernel ให้เปิด issue ที่ pstack แล้วเพิ่มแถวในตารางนี้
พร้อมระบุว่าเราติดจริงหรือมี workaround — ทีมอื่นจะได้ไม่ไปชนของเดิมซ้ำ

## ของที่รอฝั่ง agent-platform

| upstream | เรื่อง | สถานะ |
|---|---|---|
| [agent-platform#14](https://github.com/monthop-gmail/agent-platform/issues/14) | `SubjectType` ไม่มีค่าสำหรับบันทึกของโดเมน | ✅ platform เพิ่มค่า `record` ให้แล้ว — เราย้ายจาก `artifact` มาใช้ ([ADR-0004](../decisions/0004-care-event-vocabulary.md)) |
| [agent-platform#15](https://github.com/monthop-gmail/agent-platform/issues/15) | ยังไม่มี `consent/v1` | ✅ รับเข้าเป็น ADR-0012 + publish แล้ว — implementation ของเราปรับตามครบ รวมถึงลบ field `status` ที่ contract ห้าม ([ADR-0007](../decisions/0007-consent-and-data-access.md)) |

ช่อง `gaps` ใน [`platform-contract.yaml`](../platform-contract.yaml) ว่างแล้ว — ที่ปิดไปย้ายไปอยู่ `resolved_gaps`
**เจอช่องว่างใหม่เมื่อไร เปิด issue ที่ต้นทางแล้วเพิ่มกลับเข้า `gaps` ด้วย** เพื่อให้ platform
เห็นสถานะจริงของ consumer โดยไม่ต้องมาถาม

## Contract-first — กติกาที่กันทีมชนกัน

1. อยากได้ field ใหม่จาก addon ทีมอื่น → **แก้ `contracts/` ก่อน** แล้วค่อยเขียนโค้ด
2. เปลี่ยน contract ที่ทีมอื่นใช้อยู่ = PR แยก + ต้องมี reviewer จากทีมที่ใช้
3. เพิ่ม field = additive ทำได้เลย · ลบ/เปลี่ยนความหมาย = ต้องมี ADR
4. ห้าม import ข้าม addon ตรง ๆ (`from care_addons.care_medication.models import ...`)
   — คุยกันผ่าน service function ที่ addon นั้น export หรือผ่าน event เท่านั้น
5. `ap_*` ห้ามรู้จักคำว่า patient/medication/caregiver (ADR-0003) — มี test บังคับ

## Definition of Done (ทุก PR)

- [ ] มี migration ถ้าแตะ schema (`python ../pstack/cli.py makemigration <module> -m "..."`)
- [ ] state change ทุกจุดออก audit event (ADR-0004) — ไม่มี silent update
- [ ] action ที่แตะโลกจริงประกาศ `action_risk` และผ่าน `ap_policy` (ADR-0006)
- [ ] query ข้อมูลผู้ป่วยผ่าน `scoped()` ของ `core.tenancy` ไม่ใช่ `select()` ตรง (ADR-0007)
- [ ] มี test ที่พิสูจน์ negative case ไม่ใช่แค่ happy path
- [ ] `pytest tests/ -q` และ `python conformance/drift_check.py` ผ่าน
- [ ] อ้าง ADR ที่เกี่ยวข้องใน PR description

## Definition of Done ของ MVP (จาก blueprint §26)

ทุกข้อติ๊กได้ต่อเมื่อมี **เทสหรือหลักฐานที่รันซ้ำได้** ชี้ไว้ — ไม่ใช่เพราะ "น่าจะทำได้แล้ว"

- [x] สร้าง patient / caregiver / routine / medication / appointment ได้
      → `test_api_end_to_end.py::test_full_care_loop_over_http` + scenario ของแต่ละโดเมน
- [x] agent ส่ง reminder ได้ · ผู้ป่วย acknowledge ได้ · missed ถูกตรวจพบ
      → S1 `test_s1_confirm_closes_loop_without_escalation` · S2 `test_s2_silence_escalates_to_caregiver`
- [x] escalate ไป caregiver ได้ → S2 + `care_safety` (S15) + ขั้นตอนที่ค้าง (S6)
- [x] ทุก event มี audit trail ที่ตอบได้ว่า "ทำไม agent ถึงส่งข้อความนี้"
      → `audit.trail(correlation_id)` เรียงถูกแม้เวลาเท่ากัน (`sequence_no`)
      · `test_trail_order_survives_events_that_share_a_timestamp`
- [x] tenant isolation ทำงาน (มี test ข้าม tenant แล้วต้องไม่เห็นกัน)
      → `test_tenant_isolation.py` (ชั้น app) + `conformance/rls_check.py` (ชั้น DB · 21 ตาราง)
- [x] policy จำกัด action ของ agent ได้จริง
      → S9 + **เพดานของ profile** ที่บังคับจริงแล้ว (`test_governance.py::test_profile_*`)
- [x] ไม่มี medical diagnosis/action ที่ไม่ได้รับอนุญาต
      → ยาเป็น `human_command_required` + `profile.tools.deny` + คิวอนุมัติที่ไม่มี auto-approve
      · สรุปประจำวัน/adherence มีเทสห้ามคำที่เป็นการตีความอาการ
- [x] `docker compose up` รัน PoC ได้
      → ยืนยันจริง 2026-08-19: build → 22 โมดูลขึ้นครบ → worker ลงทะเบียน `care_tick`,
        `care_daily_tick` → สร้าง tenant/patient/routine/careplan/safety ผ่าน HTTP → สรุปประจำวันออก
- [x] มี automated scenario tests → 15 ไฟล์ · S1–S15 · 119 เทส รันทั้ง sqlite และ Postgres
- [x] เชื่อมกับ `agent-platform` ผ่าน contract ที่กำหนด — เป็น consumer ตาม ADR-0006 ครบ 3 ข้อ
      ([`platform-contract.yaml`](../platform-contract.yaml) · drift check · payload check)
- [x] สร้าง Care Agent ให้ผู้ป่วยหลายคนบน platform เดียวกันได้
      → หลาย tenant/หลายผู้ป่วยในฐานข้อมูลเดียว แยกกันสองด่าน (`scoped()` + RLS)
        · `care_orchestrator` เดินรอบวันให้ทุก tenant แบบ transaction ต่อ tenant

**MVP ครบตามนิยามของ blueprint แล้ว** — สิ่งที่เหลือคือ M6 (connector ข้ามองค์กร)
และงาน hardening ที่ไม่ได้อยู่ในนิยาม MVP

## Scenario tests ที่ต้องมี (ไม่ใช่ unit test)

```
S1  ผู้ป่วยยืนยันกินยา                    → confirmed, ไม่มี escalation
S2  ผู้ป่วยเงียบ                          → retry → missed → caregiver ถูกแจ้ง
S3  ตื่นมาถามวันที่ ถามซ้ำ 3 ครั้ง          → ตอบเหมือนเดิมทุกครั้ง
S4  หมอ A เพิ่มยา หมอ B ลดยาตัวเดียวกัน     → conflict, ไม่เลือกข้าง, ต้อง reconcile
S5  นัดตรวจเลือดพรุ่งนี้                    → preparation checklist ครบขั้น + escalate ถ้าค้าง
S6  เข้าเครื่องซักผ้าแล้วไม่กด start        → task stalled → เตือน → caregiver
S7  ถาม "กินยาแล้วยัง" โดยไม่มีหลักฐาน       → ตอบว่าไม่มีข้อมูล (ห้ามเดา)
S8  caregiver ของ tenant อื่นพยายามอ่าน     → ถูกปฏิเสธที่ชั้น tenancy
S9  agent พยายามแก้ medication เอง          → ถูก policy ปฏิเสธ (human_command_required)
S10 ซื้ออาหารซ้ำทั้งที่ของยังไม่หมดอายุ       → เตือนว่ามีอยู่แล้ว (ไม่ห้ามซื้อ)
S11 agent เสนอยา แล้วไม่มีใครกดอนุมัติ      → ค้างในคิวตลอดกาล ยาไม่เปลี่ยน ห้าม auto-approve
S12 สองทุ่มตามเวลาบ้านผู้ป่วย                → ผู้ดูแลได้สรุปข้อเท็จจริงของวัน วันละครั้ง
S13 หมอสั่ง "เดินวันละ 20 นาที"             → จด → เข้าคิว → คนยืนยัน → เกิดเป็นงานจริงทุกวัน
S14 "ชุดนี้ใส่แล้วหรือยัง" — จำไม่ได้        → ใส่ตะกร้าผ้าใช้แล้วก่อน (ไม่เดาว่าสะอาด)
S15 wearable แจ้งว่าอาจล้ม (มั่นใจ 93%)     → ปลุกทุกคน · ถ้ามั่นใจ 35% บันทึกไว้แต่ไม่ปลุก
```

Adversarial tests ที่ blueprint สั่งไว้: LLM hallucination · wrong patient · wrong medication ·
duplicate reminder · stale memory · unauthorized access · cross-tenant access · false safety alert ·
agent loop · notification storm

ที่มีเทสบังคับแล้ว: wrong patient/cross-tenant (`test_tenant_isolation`) · unauthorized access
(consent + RLS) · wrong medication (S4 conflict) · duplicate reminder + notification storm
(aggregation window · dedup ของสัญญาณ · `stalled_reported_at`) · stale memory (S3, S7) ·
**false safety alert** (`min_confidence_to_escalate` — S15)

## Working agreement

- ภาษาในโค้ด/commit: อังกฤษ · ภาษาในเอกสาร/ADR: ไทย (ตามแบบ `agent-platform`)
- branch: `<team>/<addon>/<สิ่งที่ทำ>` เช่น `b/care-medication/version-chain`
- ทุก PR ต้องมี reviewer จากทีม A ถ้าแตะ `ap_*` หรือ `contracts/`
- อัปเกรด `PSTACK_REF` เป็น PR แยก ห้ามปนกับงาน feature
