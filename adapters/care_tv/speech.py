"""TTS เป็น protocol — ตัวจริงของแต่ละยี่ห้อ implement เอง"""

from __future__ import annotations

from typing import Protocol


class Speaker(Protocol):
    def say(self, text: str) -> None: ...


class NullSpeaker:
    """ใช้ใน CI และบนอุปกรณ์ที่ปิดเสียง — เก็บไว้ให้ตรวจได้ว่าจะพูดอะไร"""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def say(self, text: str) -> None:
        self.spoken.append(text)
