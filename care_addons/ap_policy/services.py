"""ตัวห่อ action ของโดเมน — ทุก action ที่แตะโลกจริงต้องผ่านที่นี่

    @care_action("medication.regimen.write", autonomous=False)
    async def create_version(session, scope, ..., decision=None): ...

สิ่งที่ decorator ทำให้เสมอ:
  1. ประเมิน policy จาก capability (fail closed ถ้าไม่ได้ประกาศ → critical)
  2. ออก audit event GOVERNANCE_DECISION พร้อม policy_result (ADR-0010: บันทึกทั้ง risk และ authority)
  3. ปฏิเสธทันทีถ้า agent ลงมือเองไม่ได้ และ action นั้นประกาศตัวว่าเป็น autonomous
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from care_addons.ap_audit import services as audit
from care_addons.ap_policy.engine import Decision, PolicyDenied, evaluate
from care_addons.ap_tenancy.ids import new_id

# capability ที่ประกาศไว้จริงในโค้ด — ใช้ตรวจว่ามี action ไหนลืมประกาศ (tests/)
DECLARED: dict[str, dict[str, Any]] = {}


def care_action(
    capability: str,
    *,
    autonomous: bool = True,
    subject_type: str = "tool_call",
) -> Callable:
    """ประกาศ capability ของ action

    autonomous=True   agent ลงมือเองได้ถ้า policy อนุญาต (auto/notify) — ไม่อนุญาตแล้ว raise
    autonomous=False  action นี้ตั้งใจให้ต้องมีคนเกี่ยวข้อง (เช่นสร้าง proposal) — ไม่ raise
                      แต่ผู้เรียกต้องเช็ค decision.requires_human เอง
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        DECLARED[capability] = {"function": f"{fn.__module__}.{fn.__qualname__}", "autonomous": autonomous}
        accepts_decision = "decision" in inspect.signature(fn).parameters

        @functools.wraps(fn)
        async def wrapper(session: Any, scope: Any, *args: Any, **kwargs: Any) -> Any:
            decision: Decision = evaluate(capability)
            await audit.emit(
                session,
                scope,
                event_type="GOVERNANCE_DECISION",
                subject_type=subject_type,
                subject_id=new_id("act"),
                policy_result=decision.as_policy_result(),
                attributes={"capability": capability, "reason": decision.reason},
            )
            if autonomous and not decision.may_act_now:
                raise PolicyDenied(decision)
            if accepts_decision:
                kwargs["decision"] = decision
            return await fn(session, scope, *args, **kwargs)

        wrapper.__care_capability__ = capability  # type: ignore[attr-defined]
        return wrapper

    return decorator
