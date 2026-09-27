"""transport ระหว่าง care API กับอุปกรณ์ในบ้าน

🔒 **ทิศทางสำคัญกว่าเทคโนโลยี** — ข้อความออกทำงานได้เพราะเราเป็นคนเรียกออก
   (LINE อยู่บนคลาวด์ เรียกถึงได้) แต่ TV อยู่ในบ้านคน หลัง NAT เราเรียกเข้าไปไม่ได้
   และ device action ต้องไปถึงอุปกรณ์ · อุปกรณ์จึงต้องเป็นฝ่ายเชื่อมออกมา

ผลที่ตามมาและต้องพูดให้ตรง: `pause` เป็น audited exception เพราะ**ความเร็วคือคุณสมบัติ
ด้านความปลอดภัย** แต่ถ้า transport เป็น poll ทุก N วินาที **SLA จริงถูกกำหนดโดย
transport ไม่ใช่โดย policy** · `benchmark.py` มีไว้เพื่อให้ตัวเลขนั้นวัดได้ ไม่ใช่เดา
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4


@dataclass
class Envelope:
    """งานหนึ่งชิ้นที่ต้องไปถึงอุปกรณ์

    🔒 `envelope_id` มีเพื่อให้ฝั่งรับ **ตัดซ้ำได้** · transport จริงบน HTTP เป็น
       at-least-once เสมอ (ส่งแล้ว ack หาย → ส่งซ้ำ) และการสั่ง `pause` ซ้ำคือ
       **การกระทำต่อโลกจริงสองครั้ง** ไม่ใช่การเขียนค่าเดิมทับ

    สองเวลาในใบนี้ใช้นาฬิกาต่างกัน และตั้งใจให้ต่าง:

    * `queued_at` — `perf_counter()` · ใช้วัด latency ในกระบวนการเดียวเท่านั้น
    * `expires_at` — epoch (`time.time()`) · เป็นกำหนดตายที่ต้องเทียบกันได้
      **ข้ามเครื่องและข้ามการรีบูต** ซึ่ง `perf_counter` ทำไม่ได้

    🔒 `expires_at` เป็น `None` ได้ และค่า `None` หมายถึง "ไม่มีกำหนดตาย"
       adapter **ห้ามคิด TTL ขึ้นมาเอง** — กำหนดตายเป็นการตัดสินของโดเมน
    """

    kind: str                   # "present" | "device_action"
    payload: dict
    queued_at: float = field(default_factory=time.perf_counter)
    envelope_id: str = field(default_factory=lambda: uuid4().hex)
    expires_at: float | None = None
    # code จากทะเบียนปิดฝั่งโดเมน (`care_endpoint.expiry.CLASSES`) — ใส่ metrics ได้ ไม่มี PII
    expiry_class: str | None = None
    # 🔒 สายงานเดียวกัน: ใบที่ revision ต่ำกว่าถูกแทนแล้ว · `None` = ไม่มีใครแทนได้
    stream: str | None = None
    revision: int | None = None


class Transport(Protocol):
    """อินเทอร์เฟซเดียวกันสำหรับ poll วันนี้ และ stream/push ทีหลัง

    การเปลี่ยนจาก poll ไป stream ต้องไม่ทำให้ฝั่ง adapter ที่เรียกใช้ต้องแก้
    """

    async def publish(self, envelope: Envelope) -> None: ...
    async def next_batch(self) -> list[Envelope]: ...


class InMemoryQueue:
    """คิวที่ care ฝั่งเซิร์ฟเวอร์ถือไว้ — ใน production เป็นตาราง/broker"""

    def __init__(self) -> None:
        self._items: deque[Envelope] = deque()

    def put(self, envelope: Envelope) -> None:
        self._items.append(envelope)

    def drain(self) -> list[Envelope]:
        items, self._items = list(self._items), deque()
        return items

    def __len__(self) -> int:
        return len(self._items)


class PollingTransport:
    """อุปกรณ์ถามเป็นระยะ — ไม่ต้องเปิดพอร์ตในบ้าน

    🔒 ไม่มีการ "รออนุมัติ" ในเส้นนี้เลย · `publish` ใส่คิวทันทีทุกกรณี
       การหยุดจอที่ต้องรอใครก่อนเข้าคิว เท่ากับการหยุดที่ไม่หยุด (ADR-0015 ข้อ 2)
    """

    def __init__(self, queue: InMemoryQueue, *, interval: float) -> None:
        self.queue = queue
        self.interval = interval
        self.polls = 0

    async def publish(self, envelope: Envelope) -> None:
        self.queue.put(envelope)

    async def next_batch(self) -> list[Envelope]:
        await asyncio.sleep(self.interval)
        self.polls += 1
        return self.queue.drain()


class StreamTransport:
    """ที่ทางของ push ในอนาคต — ยังไม่ implement โดยเจตนา

    เขียนไว้เป็นรูปเพื่อให้เห็นว่า interface รองรับได้โดยผู้เรียกไม่ต้องแก้
    แต่ **ไม่ pretend ว่ามีของ** — ชั้นจัดการ connection ยังไม่มีในระบบนี้
    """

    def __init__(self, queue: InMemoryQueue) -> None:
        self.queue = queue

    async def publish(self, envelope: Envelope) -> None:
        raise NotImplementedError(
            "stream transport ยังไม่มีชั้นจัดการ connection — ใช้ PollingTransport "
            "และดูตัวเลข latency จริงที่ adapters/care_tv/benchmark.py"
        )

    async def next_batch(self) -> list[Envelope]:
        raise NotImplementedError("ดูข้อความใน publish()")
