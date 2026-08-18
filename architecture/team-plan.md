# Team Plan

เอกสารนี้คือสิ่งที่ทุกทีมใช้ร่วมกัน — **อ่านก่อนเปิด branch แรก**

## หน่วยของงานคือ addon

หนึ่ง addon = หนึ่งเจ้าของ = merge แยกกันได้ = migration ของตัวเอง (`alembic_version_<module>`)
ทีมไม่ต้องรอกันที่ระดับไฟล์ ต้องรอกันแค่ที่ระดับ **contract** เท่านั้น

```
care_addons/
├── ap_tenancy/       ทีม A   Tenant/Workspace/Consent + tenant-scoped access
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
├── care_safety/      ทีม D   sensor/IoT/GPS intake (M5)
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
      ap_tenancy · ap_audit · ap_policy
      DoD: tenant isolation มี test พิสูจน์ · ทุก state change มี event · action ที่ไม่ประกาศ risk ถูกปฏิเสธ

M2 ── Care Loop (ทีม B ขนานกับ ทีม C)
      B: care_patient → care_routine → care_medication → care_appointment
      C: care_journal → care_orientation (ทั้งคู่พึ่งแค่ ap_* ทำขนานได้ทันที)
      DoD: reminder → ack → missed → escalate ครบวง มี scenario test

M3 ── Escalation & Prep (A+B+C)
      care_orchestrator · care_escalation · ap_approval · care_appt_prep · care_careplan
      DoD: daily summary ส่งได้ · approval ค้างได้ตลอดกาลโดยไม่มี auto-approve

M4 ── Intelligence & Channels (C+E)
      personal memory/RAG · conversational interface · LINE เต็มรูปแบบ · caregiver dashboard
      DoD: ถามอะไรที่ไม่มีหลักฐาน ต้องตอบว่าไม่มีข้อมูล (มี adversarial test)

M5 ── Daily Living & Safety (D)
      care_activity · care_inventory · care_home · care_safety + IoT/wearable connector

M6 ── Multi-organization (A+E)
      clinic/hospital/pharmacy connector · care plan ข้ามองค์กร · compliance hardening
```

**เส้นทางวิกฤต:** M0 → M1 เท่านั้น ทุกทีมที่เหลือขนานกันได้หลัง M1 เพราะพึ่ง `ap_*` เหมือนกันหมด

## สถานะปัจจุบัน (2026-08-18)

**เดินได้แล้ว** — `docker compose up` ขึ้น, `pytest` 32 เทสผ่าน, drift check ผ่าน

| addon | สถานะ |
|---|---|
| `ap_tenancy` | ✅ tenant/workspace/membership/consent + tenant guard + FakeClock |
| `ap_audit` | ✅ append-only store + intake validation + `/trail/{correlation_id}` |
| `ap_policy` | ✅ authority_map + floor + `@care_action` + catalog endpoint |
| `care_patient` | ✅ patient/caregiver/care team/care profile |
| `care_escalation` | ✅ closed loop เต็มวง: remind → backoff → ask → missed → escalate + quiet hours + aggregation |
| `care_routine` | ✅ routine/มื้ออาหาร → materialize เป็น job (idempotent) + แผนวันนี้ |
| `care_medication` | ✅ version chain, meal relation, prescriber, conflict detection, reconciliation summary |
| `care_journal` | ✅ อาการ/คำถามถึงหมอ + visit brief |
| `care_appointment` | ✅ นัดหมาย + reminder ล่วงหน้า + **preparation checklist** + visit brief + บันทึกผลหลังพบหมอ |
| `care_orientation` | ✅ 5 ชั้น (เวลา/วันที่/สถานที่/คน/แผน) + daily brief + temporal memory ("พรุ่งนี้") |
| `ap_approval` · `care_careplan` · `care_activity` · `care_inventory` · `care_home` · `care_safety` · `care_orchestrator` | ⬜ ยังไม่เริ่ม |

> **หมายเหตุ:** `care_appt_prep` ที่เคยวางไว้แยก ถูกรวมเข้า `care_appointment` แล้ว
> เพราะ `contracts/appointment/v1` นิยาม `PreparationStep` เป็นส่วนหนึ่งของนัดหมาย
> และการแยก addon จะทำให้ต้อง import model ข้ามกันซึ่งผิดกติกาข้อ 4 — **อย่าสร้างซ้ำ**

**งานที่ต้องทำก่อน production (เรียงตามความเร่งด่วน):**

1. ✅ ~~ใส่ LICENSE (MIT) ที่ `willpower-institute/pstack`~~ — เสร็จ 2026-08-18,
   pin `PSTACK_REF=v0.1.1` ซึ่งเป็น tag แรกที่มีสัญญาอนุญาต
2. ✅ ~~Alembic migration ต่อ addon~~ — เสร็จ 2026-08-18, ทุกโมดูลที่มีตารางมี migration
   ของตัวเองแล้ว และ `conformance/migration_check.py` บังคับใน CI ว่าแก้ models แล้วต้องมี revision
3. ✅ ~~ทดสอบบน Postgres จริงใน CI~~ — เสร็จ 2026-08-18, CI เป็น matrix `sqlite` + `postgres`
4. 🟡 ผูก `line_oa` ของ pstack เป็นช่องทางจริงของผู้ป่วย (ตอนนี้ notification ลง DB อย่างเดียว)
5. 🟡 ตั้ง ARQ worker ให้เรียก `care_tick` เป็นระยะใน docker-compose (job เขียนไว้แล้วที่ `care_escalation/jobs.py`)

## ของที่รอฝั่ง pstack

สิ่งที่ kernel ยังไม่มีและเราแก้เองในรีโปนี้ไม่ได้ (ห้ามแก้โค้ด pstack ที่นี่ — [ADR-0002](../decisions/0002-runtime-on-pstack.md))
ติดตามที่ issue ข้างล่าง **อย่าเปิดรอบใหม่ในนี้ ให้ไปคุยที่ต้นทาง**

| upstream | เรื่อง | สถานะ |
|---|---|---|
| [pstack#2](https://github.com/willpower-institute/pstack/issues/2) | ลงทะเบียน periodic/cron job ไม่ได้ | ✅ **แก้แล้วใน pstack v0.2.0** — `care_tick` เป็น `@periodic_job` แล้ว worker เดินลูปเองทุกนาที |
| [pstack#1](https://github.com/willpower-institute/pstack/issues/1) | loader ไม่สร้างตารางถ้าโมดูลถูก import ก่อน `create_app()` | ✅ **แก้แล้วใน pstack v0.2.0** — ถอด workaround `_ensure_all_tables()` ออกจาก conftest แล้ว |
| [pstack#4](https://github.com/willpower-institute/pstack/issues/4) | worker service ใน compose พังเพราะ `arq` เป็น console script | 🟠 เลี่ยงแล้วด้วย `python -m arq` ใน compose ของเรา รอ fix ต้นทาง |
| [pstack#3](https://github.com/willpower-institute/pstack/issues/3) | multi-tenancy ใน kernel (Phase 5) | 🟡 ไม่ติด — เคาะแล้ว: RLS + คง `scoped()` · consent คงไว้ที่ repo นี้ ([ADR-0007](../decisions/0007-consent-and-data-access.md)) · kernel จะชื่อ `tenancy` (ตัด `ap_`) เมื่อยกขึ้นแล้วเราลบ `ap_tenancy` |
| [pstack-app-template#1](https://github.com/willpower-institute/pstack-app-template/issues/1) | Dockerfile ของ template copy แค่ addons | ✅ แก้ทั้งสองฝั่งแล้ว |

**กติกา:** เจอข้อจำกัดของ kernel ให้เปิด issue ที่ pstack แล้วเพิ่มแถวในตารางนี้
พร้อมระบุว่าเราติดจริงหรือมี workaround — ทีมอื่นจะได้ไม่ไปชนของเดิมซ้ำ

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
- [ ] query ข้อมูลผู้ป่วยผ่าน helper ของ `ap_tenancy` ไม่ใช่ `select()` ตรง (ADR-0007)
- [ ] มี test ที่พิสูจน์ negative case ไม่ใช่แค่ happy path
- [ ] `pytest tests/ -q` และ `python conformance/drift_check.py` ผ่าน
- [ ] อ้าง ADR ที่เกี่ยวข้องใน PR description

## Definition of Done ของ MVP (จาก blueprint §26)

- [ ] สร้าง patient / caregiver / routine / medication / appointment ได้
- [ ] agent ส่ง reminder ได้ · ผู้ป่วย acknowledge ได้ · missed ถูกตรวจพบ
- [ ] escalate ไป caregiver ได้
- [ ] ทุก event มี audit trail ที่ตอบได้ว่า "ทำไม agent ถึงส่งข้อความนี้"
- [ ] tenant isolation ทำงาน (มี test ข้าม tenant แล้วต้องไม่เห็นกัน)
- [ ] policy จำกัด action ของ agent ได้จริง
- [ ] ไม่มี medical diagnosis/action ที่ไม่ได้รับอนุญาต
- [ ] `docker compose up` รัน PoC ได้
- [ ] มี automated scenario tests
- [ ] เชื่อมกับ `agent-platform` ผ่าน contract ที่กำหนด (drift check ผ่าน)
- [ ] สร้าง Care Agent ให้ผู้ป่วยหลายคนบน platform เดียวกันได้

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
```

Adversarial tests ที่ blueprint สั่งไว้: LLM hallucination · wrong patient · wrong medication ·
duplicate reminder · stale memory · unauthorized access · cross-tenant access · false safety alert ·
agent loop · notification storm

## Working agreement

- ภาษาในโค้ด/commit: อังกฤษ · ภาษาในเอกสาร/ADR: ไทย (ตามแบบ `agent-platform`)
- branch: `<team>/<addon>/<สิ่งที่ทำ>` เช่น `b/care-medication/version-chain`
- ทุก PR ต้องมี reviewer จากทีม A ถ้าแตะ `ap_*` หรือ `contracts/`
- อัปเกรด `PSTACK_REF` เป็น PR แยก ห้ามปนกับงาน feature
