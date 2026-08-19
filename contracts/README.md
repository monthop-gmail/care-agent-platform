# contracts/

Contract ของ **โดเมนนี้** เท่านั้น — YAML / JSON Schema, tech-neutral, ไม่มีโค้ด

## กติกา

- `$ref` ไปที่ [`agent-platform`](https://github.com/monthop-gmail/agent-platform/tree/main/contracts)
  สำหรับทุกอย่างที่ platform นิยามไว้แล้ว: `TenantId` · `Principal` · `RequestContext` ·
  `ActionRisk` · `Authority` · `Effect` — **ห้ามนิยามซ้ำเอง** ([ADR-0001](../decisions/0001-consumer-of-agent-platform.md))
- เพิ่ม field = additive ทำได้เลย · ลบ/เปลี่ยนความหมาย = ต้องมี ADR + reviewer จากทีมที่ใช้
- เปลี่ยน contract ที่ทีมอื่นใช้อยู่ ต้องเป็น PR แยก ไม่ปนกับ implementation
- `conformance/drift_check.py` ตรวจว่า `$ref` ทุกตัวยังชี้ไปที่ contract ที่มีจริงในเวอร์ชันที่ pin

## โครงสร้าง

| contract | เจ้าของ | milestone |
|---|---|---|
| [`event/v1`](event/v1) | ทีม A | M1 |
| [`consent/v1`](consent/v1) | ทีม A | M1 |
| [`patient/v1`](patient/v1) | ทีม B | M2 |
| [`routine/v1`](routine/v1) | ทีม B | M2 |
| [`medication/v1`](medication/v1) | ทีม B | M2 |
| [`appointment/v1`](appointment/v1) | ทีม B/C | M2–M3 |
| [`journal/v1`](journal/v1) | ทีม C | M2 |
| [`careplan/v1`](careplan/v1) | ทีม C | M3 |
| [`activity/v1`](activity/v1) | ทีม D | M5 |
| [`inventory/v1`](inventory/v1) | ทีม D | M5 |
| [`home/v1`](home/v1) | ทีม D | M5 |
| [`safety/v1`](safety/v1) | ทีม D | M5 |
| [`escalation/v1`](escalation/v1) | ทีม A+B | M3 |

## เวอร์ชันของ agent-platform ที่ pin

ดู [`../conformance/pinned.yaml`](../conformance/pinned.yaml)
