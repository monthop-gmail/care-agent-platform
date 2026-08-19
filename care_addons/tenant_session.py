"""ผูก tenant เข้ากับ session ให้ RLS ทำงานข้าม commit

**ไม่ใช่ addon** (ไม่มี `__manifest__.py`) — loader มองข้ามไฟล์นี้ เป็นแค่ helper กลาง
ที่ทุก entry point ของ repo นี้ใช้ร่วมกัน

## ปัญหาที่แก้

`core.tenancy.set_tenant()` ของ kernel ตั้ง GUC ด้วย `set_config(..., is_local=true)`
ซึ่ง **มีอายุแค่ transaction ปัจจุบัน** — ถูกต้องแล้วสำหรับ connection pool (ค่าไม่รั่วข้าม request)
แต่แปลว่าโค้ดแบบนี้พังเงียบ ๆ:

    await set_tenant(session, tenant_id)
    await do_something(session)
    await session.commit()        # ← GUC หายไปพร้อม transaction
    await read_more(session)      # ← เห็น 0 แถว ไม่มี error

เจอจริงตอนเปิด RLS: เทสที่ commit ระหว่างทาง 42 ตัวกลายเป็น "ไม่พบผู้ป่วย"
ทั้งที่ข้อมูลอยู่ครบ (care-agent-platform#4)

## วิธีแก้

ผูก tenant ไว้กับ **session** แล้วตั้ง GUC ใหม่อัตโนมัติทุกครั้งที่เปิด transaction ใหม่
ผ่าน event `after_begin` ของ SQLAlchemy

    await bind_tenant(session, "t-family-a")   # ตั้งให้เดี๋ยวนี้ + ทุก transaction ถัดไป
    ...
    await session.commit()
    ...                                        # ยังเห็นข้อมูลของ tenant เดิม

🔒 session ที่ทำงานให้หลาย tenant (เช่น worker) ต้อง `bind_tenant` ใหม่ทุกครั้งที่เปลี่ยน tenant
   และ **commit ให้จบก่อนเปลี่ยน** ไม่งั้นงานของสอง tenant จะอยู่ใน transaction เดียวกัน
"""

from __future__ import annotations

from core.tenancy import TENANT_GUC, set_tenant
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

# เก็บ tenant ไว้ที่ `session.info` ไม่ใช่ dict ระดับโมดูลที่คีย์ด้วย id(session)
# — id ของ object ถูกใช้ซ้ำได้หลัง GC ทำให้ session ใหม่รับ binding ของ session ที่ตายไปแล้ว
#   (เจอจริง: เทสผ่านตอนรันเดี่ยว แต่พังตอนรันรวมเพราะ id ชนกัน)
INFO_KEY = "care_tenant_id"


def _apply_on_begin(session, transaction, connection) -> None:
    tenant_id = session.info.get(INFO_KEY)
    if tenant_id is None or connection.dialect.name != "postgresql":
        return
    connection.execute(text("SELECT set_config(:k, :v, true)"), {"k": TENANT_GUC, "v": tenant_id})


async def bind_tenant(session: AsyncSession, tenant_id: str) -> None:
    """ตั้ง GUC เดี๋ยวนี้ และตั้งให้อัตโนมัติทุก transaction ถัดไปของ session นี้"""
    sync_session = session.sync_session
    if not event.contains(sync_session, "after_begin", _apply_on_begin):
        event.listen(sync_session, "after_begin", _apply_on_begin)
    sync_session.info[INFO_KEY] = tenant_id
    await set_tenant(session, tenant_id)


def unbind_tenant(session: AsyncSession) -> None:
    """เลิกผูก — ใช้ตอนคืน session เข้า pool หรือจบเทส"""
    sync_session = session.sync_session
    sync_session.info.pop(INFO_KEY, None)
    if event.contains(sync_session, "after_begin", _apply_on_begin):
        event.remove(sync_session, "after_begin", _apply_on_begin)
