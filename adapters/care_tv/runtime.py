"""loop ที่รันจริงของ adapter — poll · dispatch · lifecycle

มติที่ใบนี้ยืนบน:
* `dec-3493b67e` — baseline คือ **polling 5 วินาที** พร้อมเปิดเผยตัวเลข latency ที่วัดได้
  และ **ห้ามเรียกว่า instant**
* `dec-ad4485af` — โค้ดอยู่ใน care-agent-platform จนเริ่มมีโค้ด vendor

🔒 loop นี้ไม่รู้จัก careplan · medication · policy · approval · audit · consent เลย
   มันรู้แค่ว่า envelope มีสองชนิดและต้องส่งไปทางไหน — เทสบังคับข้อนี้อยู่
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from adapters.care_tv import actions
from adapters.care_tv.prompts import PromptBook
from adapters.care_tv.speech import NullSpeaker, Speaker
from adapters.care_tv.transport import Envelope, InMemoryQueue, PollingTransport

logger = logging.getLogger(__name__)

# ── ตัวเลขที่ **วัดได้จริง** จาก adapters/care_tv/benchmark.py ─────────────────
#
# 🔒 ไม่ใช่ค่าที่ประมาณเอา · ทำซ้ำได้ด้วย `python adapters/care_tv/benchmark.py --full`
#    seed คงที่ · เครื่อง dev ตัวเดียว · เก็บไว้ที่นี่เพื่อให้ผู้เรียกใช้เห็นข้อจำกัด
#    ตรงจุดที่เขาเลือกรอบ poll ไม่ใช่ต้องไปเปิดเอกสารสถาปัตยกรรม
MEASURED_LATENCY = {
    1.0: {"p50": 0.469, "p95": 0.915, "max": 0.982},
    5.0: {"p50": 2.229, "p95": 4.501, "max": 4.501},
    15.0: {"p50": 8.466, "p95": 14.217, "max": 14.217},
    30.0: {"p50": 10.098, "p95": 25.489, "max": 25.489},
}
MVP_INTERVAL = 5.0          # dec-3493b67e

# จำ id ที่เคยทำแล้วเท่านี้ — พอสำหรับการส่งซ้ำที่เกิดจริง และไม่โตไม่รู้จบบนกล่องทีวี
SEEN_LIMIT = 512


def disclosure(interval: float = MVP_INTERVAL) -> str:
    """ประโยคที่ต้องติดไปกับทุกที่ที่พูดถึงความเร็วของการหยุดจอ

    🔒 `dec-3493b67e` บังคับให้เปิดเผยตัวเลขที่วัดได้ · ข้อความนี้จึงไม่ใช่คำโฆษณา
       และไม่มีคำว่า "ทันที" ในรูปคำกล่าวอ้าง
    """
    measured = MEASURED_LATENCY.get(interval)
    if measured is None:
        return (
            f"รอบ poll {interval}s ยังไม่ถูกวัด — ห้ามกล่าวอ้างความเร็วของการหยุดจอ "
            f"จนกว่าจะรัน adapters/care_tv/benchmark.py กับรอบนี้"
        )
    return (
        f"รอบ poll {interval}s · latency ที่วัดได้ p50 {measured['p50']}s "
        f"p95 {measured['p95']}s max {measured['max']}s · "
        f"การหยุดจอ **ไม่ใช่การหยุดที่เกิดขึ้นพร้อมคำสั่ง** — "
        f"SLA จริงถูกกำหนดโดยรอบ poll ไม่ใช่โดย policy"
    )


@dataclass
class RuntimeStats:
    polls: int = 0
    presented: int = 0
    actions_done: int = 0
    failures: list[str] = field(default_factory=list)
    reconnects: int = 0
    duplicates: int = 0
    expired: int = 0
    superseded: int = 0
    # 🔒 metrics แยกตาม **code** ของชนิดงาน ไม่ใช่ตามผู้ป่วย — ไม่มี PII ในตัวนับ
    expired_by_class: dict[str, int] = field(default_factory=dict)


class AdapterRuntime:
    """เริ่ม หยุด และกลับมาเชื่อมต่อใหม่เมื่อเน็ตหลุด

    🔒 `stop()` **ไม่ดึงงานออกจากคิว** — งานที่ยังไม่ถูกส่งต้องอยู่ต่อ ไม่ใช่หายไปกับ
       การปิดแอป · ถ้าหายไป ผู้ป่วยจะไม่ได้รับการเตือนโดยไม่มีใครรู้ว่าเพราะอะไร
    """

    def __init__(
        self,
        transport: PollingTransport,
        *,
        controller: actions.DeviceController | None = None,
        speaker: Speaker | None = None,
        backoff_base: float = 0.5,
        backoff_cap: float = 30.0,
        clock=time.time,
        prompts: PromptBook | None = None,
    ) -> None:
        self.transport = transport
        self.controller = controller or actions.RecordingController()
        self.speaker = speaker or NullSpeaker()
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.prompts = prompts or PromptBook()
        self.clock = clock          # ฉีดได้เพื่อให้เทสกำหนดตายโดยไม่ต้องรอเวลาจริง
        self.stats = RuntimeStats()
        self._stopping = False
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._revision: OrderedDict[str, int] = OrderedDict()

    # ── idempotency · กำหนดตาย ──────────────────────────────────────────────
    def _already_done(self, envelope: Envelope) -> bool:
        """ส่งซ้ำต้องไม่กลายเป็นการกระทำซ้ำ

        🔒 ตัดซ้ำอยู่ที่ **ฝั่งรับ** ไม่ใช่ที่คิว เพราะการส่งซ้ำเกิดหลังคิวปล่อยของไปแล้ว
        """
        if envelope.envelope_id in self._seen:
            self.stats.duplicates += 1
            logger.info("ข้าม envelope ซ้ำ %s (%s)", envelope.envelope_id[:8], envelope.kind)
            return True
        self._seen[envelope.envelope_id] = None
        while len(self._seen) > SEEN_LIMIT:
            self._seen.popitem(last=False)
        return False

    def _too_late(self, envelope: Envelope) -> bool:
        """ของที่เลยกำหนดตายต้องไม่ถูกทำย้อนหลัง

        🔒 นี่คือความหมายของ "offline" ในระบบนี้ · เครื่องดับไปสี่สิบนาทีแล้วกลับมา
           การหยุดจอตามคำสั่งเก่าไม่ใช่การทำงานที่ค้างไว้ให้เสร็จ — มันคือ
           **การกระทำที่เหตุผลหมดอายุไปแล้ว** และผู้ป่วยเป็นคนรับผล

        และของที่ถูกทิ้งต้อง **นับให้เห็น** ไม่ใช่หายเงียบ
        """
        if envelope.expires_at is None:
            return False
        if self.clock() <= envelope.expires_at:
            return False
        self.stats.expired += 1
        cls = envelope.expiry_class or "undeclared"
        self.stats.expired_by_class[cls] = self.stats.expired_by_class.get(cls, 0) + 1
        logger.warning(
            "ทิ้ง envelope ที่เลยกำหนดตาย %s (%s) — ไม่ทำย้อนหลัง",
            envelope.envelope_id[:8], envelope.kind,
        )
        return True

    def _superseded(self, envelope: Envelope, newest: dict[str, int] | None = None) -> bool:
        """ใบเก่าของสายงานเดียวกันถูกแทนแล้ว — ไม่ต้องขึ้นจอซ้อนกัน

        🔒 เตือนครั้งที่สองของงานเดียวกันคือ **ใบแทน** ไม่ใช่ใบเพิ่ม · ถ้าปล่อยทั้งสองใบ
           ผู้ป่วยเห็นคำเตือนเรื่องเดียวกันสองอันและไม่รู้ว่าอันไหนคืออันที่ต้องตอบ

        `stream = None` แปลว่าไม่มีใครแทนได้ — คำสั่งต่ออุปกรณ์แต่ละใบเป็นคำสั่งของตัวเอง
        """
        if envelope.stream is None or envelope.revision is None:
            return False
        latest = max(
            self._revision.get(envelope.stream, -1),
            (newest or {}).get(envelope.stream, -1),
        )
        latest = None if latest < 0 else latest
        if latest is not None and envelope.revision < latest:
            self.stats.superseded += 1
            logger.info(
                "ข้าม envelope ที่ถูกแทนแล้ว %s (%s rev %s < %s)",
                envelope.envelope_id[:8], envelope.stream, envelope.revision, latest,
            )
            return True
        self._revision[envelope.stream] = envelope.revision
        while len(self._revision) > SEEN_LIMIT:
            self._revision.popitem(last=False)
        return False

    # ── dispatch ────────────────────────────────────────────────────────────
    def dispatch(self, envelope: Envelope) -> None:
        """envelope มีสองชนิด และ adapter ไม่ตีความเพิ่มไปกว่านั้น"""
        if envelope.kind == "present":
            plan_dict = envelope.payload.get("plan")
            care_job_id = envelope.payload.get("care_job_id")
            # 🔒 คำถามที่รอคำตอบจากคนต้องจำกำหนดตายไว้ ไม่งั้นการกดปุ่มเมื่อไรก็ได้
            #    จะกลายเป็นหลักฐานของงานที่ปิดไปแล้ว (`prompts.py`)
            if care_job_id and plan_dict and plan_dict.get("needs_answer"):
                self.prompts.remember(care_job_id, envelope.expires_at)
            if plan_dict and plan_dict.get("speak"):
                self.speaker.say(envelope.payload.get("text", ""))
            self.stats.presented += 1
        elif envelope.kind == "device_action":
            actions.execute(self.controller, envelope.payload["action"])
            self.stats.actions_done += 1
        else:
            # ชนิดที่ไม่รู้จักต้องไม่ถูกเดา และต้องไม่ทำให้ loop ตาย
            raise actions.UnknownAction(f"envelope kind '{envelope.kind}' ไม่รู้จัก")

    # ── loop ────────────────────────────────────────────────────────────────
    async def run(self, *, max_polls: int | None = None) -> RuntimeStats:
        """`max_polls` มีเพื่อให้เทสจบได้ · บนอุปกรณ์จริงเรียกโดยไม่ใส่

        🔒 `stop()` เป็นคำสั่งที่ **ค้างอยู่** — เรียกก่อน `run()` ก็ต้องไม่เริ่ม poll
           การเริ่มใหม่คือการสร้าง runtime ใหม่ เท่ากับการเปิดแอปใหม่บนอุปกรณ์จริง
        """
        consecutive = 0
        while not self._stopping and (max_polls is None or self.stats.polls < max_polls):
            try:
                batch = await self.transport.next_batch()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # เน็ตหลุดต้องไม่ทำให้ loop ตาย · ถอยแบบทวีคูณแล้วลองใหม่
                consecutive += 1
                self.stats.reconnects += 1
                delay = min(self.backoff_base * (2 ** (consecutive - 1)), self.backoff_cap)
                logger.warning("poll ล้มเหลว (%s) — ลองใหม่ใน %.1fs", type(e).__name__, delay)
                await asyncio.sleep(delay)
                continue
            consecutive = 0
            self.stats.polls += 1
            # 🔒 **ไม่จัดลำดับ batch ใหม่** — ลำดับที่โดเมนใส่คิวมีความหมาย (หยุดจอก่อนเตือน)
            #    การหาใบใหม่สุดของแต่ละสายงานทำแยกก่อน แล้ววนตามลำดับเดิม
            newest: dict[str, int] = {}
            for e in batch:
                if e.stream is not None and e.revision is not None:
                    newest[e.stream] = max(newest.get(e.stream, e.revision), e.revision)
            for envelope in batch:
                if (
                    self._already_done(envelope)
                    or self._too_late(envelope)
                    or self._superseded(envelope, newest)
                ):
                    continue
                try:
                    self.dispatch(envelope)
                except asyncio.CancelledError:
                    # 🔒 ถูกยกเลิกกลางทาง: ถอน id ออกจาก seen เพื่อให้การส่งซ้ำยังทำได้
                    #    ไม่งั้นงานจะ "เคยทำแล้ว" ทั้งที่ยังไม่ได้ทำ
                    self._seen.pop(envelope.envelope_id, None)
                    raise
                except Exception as e:
                    # 🔒 ล้มเหลวต้องเห็นได้ ไม่ใช่หายเงียบ — และไม่ทำให้ envelope อื่นค้าง
                    self.stats.failures.append(f"{envelope.kind}: {type(e).__name__}")
                    logger.exception("dispatch ล้มเหลวสำหรับ %s", envelope.kind)
        return self.stats

    def stop(self) -> None:
        """ปิดอย่างสุภาพ — ไม่ดึงคิว ไม่ทิ้งงานที่ยังไม่ได้ส่ง"""
        self._stopping = True


def build(interval: float = MVP_INTERVAL) -> tuple[InMemoryQueue, AdapterRuntime]:
    """ประกอบชุดที่รันได้ทันทีโดยไม่มีอุปกรณ์จริง"""
    queue = InMemoryQueue()
    return queue, AdapterRuntime(PollingTransport(queue, interval=interval))


async def _demo() -> int:
    """`python -m adapters.care_tv.runtime` — เห็น loop ทำงานและเห็นข้อจำกัดของมัน"""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    queue, runtime = build(interval=0.5)      # 0.5s เพื่อให้ demo จบไว
    print(disclosure())                       # ← ตัวเลขที่วัดได้ ไม่ใช่คำโฆษณา
    queue.put(Envelope(kind="present", payload={"text": "ถึงเวลายาเช้า", "plan": {"speak": True}}))
    queue.put(Envelope(kind="device_action", payload={"action": "pause"}))
    stats = await runtime.run(max_polls=2)
    print(f"polls={stats.polls} presented={stats.presented} actions={stats.actions_done}")
    print(f"controller calls={runtime.controller.calls} spoken={runtime.speaker.spoken}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_demo()))
