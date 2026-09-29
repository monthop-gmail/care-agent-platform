"""ลงทะเบียนเป็นช่องทาง `tv` — จุดเดียวที่ adapter แตะ care

🔒 ไม่แก้โค้ดใน `care_escalation` แม้บรรทัดเดียว · `register_sender` เป็น seam ที่มีอยู่แล้ว
   และ LINE ใช้เส้นเดียวกันนี้ (`care_line/outbound.py`)

🔒 sender **ต้องไม่ raise** — ช่องทางล่มต้องไม่ทำให้ closed loop ของผู้ป่วยคนอื่นหยุดตาม
"""

from __future__ import annotations

import logging

from adapters.care_tv import render
from adapters.care_tv.speech import NullSpeaker, Speaker
from adapters.care_tv.transport import Envelope, InMemoryQueue
from care_addons.care_escalation.services import register_sender

logger = logging.getLogger(__name__)


class TvChannel:
    """ถือคิวขาออกกับตัวพูด — ตัวจริงบนอุปกรณ์ inject ของจริงเข้ามาแทน"""

    def __init__(self, queue: InMemoryQueue, *, speaker: Speaker | None = None) -> None:
        self.queue = queue
        self.speaker = speaker or NullSpeaker()

    async def send(self, session, notification) -> tuple[bool, str | None]:
        try:
            # 🔒 intent มาจาก effective_presentation() แล้ว — ไม่ประเมิน quiet hours ซ้ำ
            plan = render.plan(notification.presentation)
            self.queue.put(
                Envelope(
                    kind="present",
                    payload={
                        "notification_id": notification.id,
                        "text": notification.text,
                        "plan": None if plan is None else plan.__dict__,
                        "care_job_id": notification.care_job_id,
                    },
                    # 🔒 **คัดลอก** มาจากแถว ไม่ได้คำนวณที่นี่ — adapter ไม่มีสิทธิ์ตั้งกำหนดตาย
                    #    (`care_endpoint/expiry.py` เป็นฝ่ายตัดสิน · ADR-0016)
                    expires_at=(
                        None if notification.expires_at is None
                        else notification.expires_at.timestamp()
                    ),
                    expiry_class=notification.expiry_class,
                    # 🔒 สายงานก็ **คัดลอก** มาเช่นกัน — ใครแทนใครได้เป็นการตัดสินของโดเมน
                    #    (เดิม adapter เดาเอาจาก care_job_id ซึ่งแปลว่า orientation แทนกันไม่ได้)
                    stream=notification.stream,
                    revision=notification.id,
                )
            )
            if plan is not None and plan.speak:
                self.speaker.say(notification.text)
            return True, None
        except Exception as e:      # ห้าม raise ออกไปหา care loop
            logger.exception("ส่งเข้าคิวของ TV ไม่สำเร็จ")
            return False, f"tv adapter: {type(e).__name__}"


def install(queue: InMemoryQueue, *, speaker: Speaker | None = None) -> TvChannel:
    channel = TvChannel(queue, speaker=speaker)
    register_sender("tv", channel.send)
    return channel
