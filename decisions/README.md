# Decisions (ADR)

ทุกการตัดสินใจที่เปลี่ยน **ขอบเขตระหว่าง repo** หรือ **ข้อผูกพันเชิงความปลอดภัยของผู้ป่วย**
ต้องมี ADR ที่นี่ก่อน implement — ไม่ใช่หลัง

| # | เรื่อง | สถานะ |
|---|---|---|
| [0001](0001-consumer-of-agent-platform.md) | care-agent-platform เป็น consumer ของ agent-platform | Accepted |
| [0002](0002-runtime-on-pstack.md) | runtime อยู่บน pstack แบบ app repo (pin tag) | Accepted |
| [0003](0003-conformance-layer-in-app-repo.md) | platform conformance layer (`ap_*`) อยู่ใน repo นี้ก่อน | Accepted |
| [0004](0004-care-event-vocabulary.md) | care event vocabulary ต่อยอดจาก `event/v1` แบบ additive | Accepted |
| [0005](0005-medication-versioning.md) | medication เป็น append-only version chain ห้าม overwrite | Accepted |
| [0006](0006-ai-has-no-medical-authority.md) | AI ไม่มี medical authority — บังคับผ่าน authority_map | Accepted |
| [0007](0007-consent-and-data-access.md) | consent เป็นเงื่อนไขการเข้าถึง ไม่ใช่แค่ RBAC | Accepted |
| [0008](0008-patient-channel-is-deterministic.md) | ช่องทางของผู้ป่วยตอบแบบ deterministic ไม่ผ่าน LLM | Accepted |
| [0009](0009-approval-waits-forever.md) | คำขออนุมัติรอได้ตลอดกาล — เวลาไม่เคยอนุมัติอะไรให้ | Accepted |

## กติกา

- ADR ที่ Accepted แล้วแก้ไม่ได้ — ถ้าเปลี่ยนใจให้เขียน ADR ใหม่ที่ `Supersedes` ตัวเก่า
- ADR ที่แตะ **ขอบเขตของ `agent-platform`** ต้องไปเปิด ADR ที่ repo นั้นก่อน ที่นี่ทำได้แค่บันทึกว่าเราใช้ยังไง
- ทุก PR ที่เพิ่ม/แก้ addon ต้องอ้าง ADR ที่เกี่ยวข้องใน description
