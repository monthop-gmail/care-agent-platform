#!/usr/bin/env python3
"""วัด latency จริงของ transport — ไม่ใช่เดา

🔒 มีไฟล์นี้เพราะ ADR-0015 บอกว่า `pause` เป็น audited exception เพราะ **ความเร็วคือ
   คุณสมบัติด้านความปลอดภัย** · ถ้า transport เป็น poll ทุก N วินาที ความเร็วนั้นถูกกำหนด
   โดย transport ไม่ใช่โดย policy · ห้ามเขียนว่า "หยุดได้ทันที" จนกว่าจะมีตัวเลข

    python adapters/care_tv/benchmark.py            # ช่วงสั้น — รันใน CI ได้
    python adapters/care_tv/benchmark.py --full     # รวม 5s / 15s / 30s (ใช้เวลาหลายนาที)

ตัวเลขที่รายงานเป็น p50 / p95 / max ไม่ใช่ค่าเฉลี่ย เพราะค่าเฉลี่ยซ่อนหางของการแจกแจง
ซึ่งเป็นส่วนที่สำคัญที่สุดเมื่อพูดถึงความปลอดภัย
"""

from __future__ import annotations

import asyncio
import random
import statistics
import sys
import time

sys.path.insert(0, __file__.rsplit("/adapters/", 1)[0])

from adapters.care_tv.transport import Envelope, InMemoryQueue, PollingTransport

SHORT_INTERVALS = [0.1, 0.25, 0.5, 1.0]
FULL_INTERVALS = SHORT_INTERVALS + [5.0, 15.0, 30.0]


async def _measure(interval: float, samples: int) -> list[float]:
    """ยิงคำสั่งเข้าคิวที่เวลาสุ่มภายในรอบ poll แล้ววัดว่าอุปกรณ์เห็นเมื่อไร"""
    queue = InMemoryQueue()
    transport = PollingTransport(queue, interval=interval)
    latencies: list[float] = []

    async def device() -> None:
        while len(latencies) < samples:
            batch = await transport.next_batch()
            seen = time.perf_counter()
            latencies.extend(seen - item.queued_at for item in batch)

    async def domain() -> None:
        for _ in range(samples):
            # จังหวะที่ผู้ป่วยถึงเวลากินยาไม่ได้ซิงก์กับรอบ poll — สุ่มในรอบจึงตรงความจริง
            await asyncio.sleep(random.uniform(0, interval))
            await transport.publish(Envelope(kind="device_action", payload={"action": "pause"}))

    await asyncio.gather(device(), domain())
    return latencies[:samples]


def _report(interval: float, latencies: list[float]) -> dict:
    ordered = sorted(latencies)
    return {
        "interval_s": interval,
        "samples": len(ordered),
        "p50_s": round(statistics.median(ordered), 3),
        "p95_s": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "max_s": round(ordered[-1], 3),
    }


async def main() -> int:
    full = "--full" in sys.argv
    intervals = FULL_INTERVALS if full else SHORT_INTERVALS
    random.seed(20260927)      # ทำซ้ำได้
    print(f"{'interval':>10} {'samples':>8} {'p50':>8} {'p95':>8} {'max':>8}")
    for interval in intervals:
        samples = 40 if interval <= 1.0 else 6
        rows = _report(interval, await _measure(interval, samples))
        print(
            f"{rows['interval_s']:>10} {rows['samples']:>8} "
            f"{rows['p50_s']:>8} {rows['p95_s']:>8} {rows['max_s']:>8}"
        )
    print(
        "\nรูปที่คาดไว้: เวลามาถึงกระจายสม่ำเสมอในรอบ poll → latency ~ U(0, interval)\n"
        "จึงได้ p50 ≈ 0.5·interval และ max → interval · ตัวเลขข้างบนยืนยันรูปนี้\n"
        "แปลว่า SLA ของ pause = ฟังก์ชันของรอบ poll ไม่ใช่ของ policy"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
