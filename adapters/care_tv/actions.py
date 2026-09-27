"""ลงมือกับอุปกรณ์ — ตัวจริงของแต่ละยี่ห้อ implement `DeviceController`

🔒 adapter **ไม่ตัดสินว่าควรหยุดไหม** · โดเมนตัดสินและบันทึกไปแล้วที่ `care_endpoint`
   ที่นี่มีหน้าที่เดียวคือทำให้เกิดขึ้นจริงบนอุปกรณ์ แล้วรายงานว่าทำได้หรือไม่
"""

from __future__ import annotations

from typing import Protocol

ACTIONS = ["pause", "resume", "cancel"]


class DeviceController(Protocol):
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def cancel(self) -> None: ...


class RecordingController:
    """ใช้ใน CI — เก็บลำดับที่ถูกสั่งไว้ให้ตรวจได้ ไม่มีอุปกรณ์จริง"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")

    def cancel(self) -> None:
        self.calls.append("cancel")


class UnknownAction(ValueError):
    """คำสั่งที่ไม่รู้จักต้องไม่ถูกเดา"""


def execute(controller: DeviceController, action: str) -> str:
    if action not in ACTIONS:
        raise UnknownAction(f"action '{action}' ไม่อยู่ใน {ACTIONS}")
    getattr(controller, action)()
    return action
