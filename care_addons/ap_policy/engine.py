"""Policy engine — ตัดสินว่า action นี้ทำได้เลย ต้องแจ้ง ต้องอนุมัติ หรือคนต้องเป็นคนสั่ง

agent-platform ADR-0010:
    action_risk (static ผูกกับ capability) × authority_map (config ต่อ tenant) → authority

🔒 fail closed ทุกทาง:
    - capability ที่ไม่ได้ประกาศ action_risk → critical
    - authority ที่ไม่รู้จัก → human_command_required
    - config ที่พยายามลดต่ำกว่า floor → boot ไม่ผ่าน

🔒 โมดูลนี้ห้ามรู้จักคำว่า patient / medication / caregiver (ADR-0003 กฎข้อ 1)
   ชื่อ capability เป็นแค่ string ที่โดเมนส่งเข้ามา
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from core.clock import now

RISK_ORDER = ["low", "medium", "high", "critical"]
AUTHORITY_ORDER = ["auto", "notify", "approval_required", "human_command_required"]

FALLBACK_RISK = "critical"
FALLBACK_AUTHORITY = "human_command_required"

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "policies" / "care-authority-map.yaml"


class PolicyConfigError(RuntimeError):
    """config ผิดกติกา — ต้องหยุดตั้งแต่ boot ไม่ใช่ปล่อยให้รันแล้วอนุญาตเกิน"""


class PolicyDenied(PermissionError):
    def __init__(self, decision: Decision) -> None:
        super().__init__(
            f"action ถูกปฏิเสธ: {decision.reason} "
            f"(risk={decision.action_risk} authority={decision.authority})"
        )
        self.decision = decision


@dataclass(frozen=True)
class Decision:
    """policy/v1 Decision"""

    effect: str  # allow | deny
    authority: str
    action_risk: str
    policy_id: str
    capability: str
    reason: str = ""
    constraint: str = "none"
    evaluated_at: datetime | None = None
    # 🔒 profile ของ agent ปฏิเสธ capability นี้ — ห้ามเดินต่อไม่ว่า authority จะเป็นอะไร
    profile_denied: bool = False
    # ข้อยกเว้นที่ config ประกาศไว้อย่างเปิดเผยและต้อง audit เต็ม (เช่น emergency.escalate
    # ที่เป็น critical แต่ต้องเร็วกว่าการรอคนสั่ง — ADR-0007 ข้อ 5) · เพดานไม่ยกทับข้อนี้
    audited_exception: bool = False

    @property
    def requires_human(self) -> bool:
        return self.authority in ("approval_required", "human_command_required")

    @property
    def may_act_now(self) -> bool:
        """agent ลงมือเองได้ไหม — notify ทำได้แต่ต้องแจ้ง"""
        return self.effect == "allow" and self.authority in ("auto", "notify")

    def as_policy_result(self) -> dict:
        """รูปแบบที่ใส่ใน audit event ได้ตรง event/v1 $.policy_result"""
        return {
            "effect": self.effect,
            "authority": self.authority,
            "action_risk": self.action_risk,
            "policy_id": self.policy_id,
        }


def _load_yaml(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _rank(value: str, order: list[str]) -> int:
    return order.index(value) if value in order else len(order)


@lru_cache(maxsize=8)
def load_policy(path: str | None = None) -> Policy:
    return Policy(_load_yaml(Path(path) if path else DEFAULT_POLICY_PATH))


class Policy:
    def __init__(self, config: dict) -> None:
        self.policy_id: str = config.get("policy_id", "unknown")
        self.authority_map: dict = config.get("authority_map") or {}
        self.capabilities: dict = config.get("capabilities") or {}
        fallback = config.get("fallback") or {}
        self.fallback_authority: str = fallback.get("authority", FALLBACK_AUTHORITY)
        self.fallback_risk: str = fallback.get("action_risk", FALLBACK_RISK)
        floor = config.get("floor") or {}
        self.floor_capabilities: dict = floor.get("capabilities") or {}
        self.floor_risk: dict = floor.get("risk") or {}
        self._validate()

    def _validate(self) -> None:
        for risk, authority in self.authority_map.items():
            if risk not in RISK_ORDER:
                raise PolicyConfigError(f"action_risk ที่ไม่รู้จักใน authority_map: {risk}")
            if authority not in AUTHORITY_ORDER:
                raise PolicyConfigError(f"authority ที่ไม่รู้จัก: {authority}")
        from care_addons.ap_policy.profile import load_profile

        profile = load_profile()
        for risk, ceiling in profile.authority_map.items():
            configured = self.authority_map.get(risk)
            if configured and _rank(configured, AUTHORITY_ORDER) < _rank(ceiling, AUTHORITY_ORDER):
                raise PolicyConfigError(
                    f"authority_map[{risk}]={configured} หลวมกว่าเพดานของ profile ({ceiling}) "
                    f"— profile เป็นเพดาน ไม่ใช่การอนุญาต ค่าที่กว้างที่สุดชนะไม่ได้ (profile/v1)"
                )

        for risk, required in self.floor_risk.items():
            configured = self.authority_map.get(risk)
            if configured and _rank(configured, AUTHORITY_ORDER) < _rank(required, AUTHORITY_ORDER):
                raise PolicyConfigError(
                    f"authority_map[{risk}]={configured} หลวมกว่าเพดาน {required} "
                    f"— config ตั้งให้เข้มขึ้นได้ แต่ลดกว่าเพดานไม่ได้ (ADR-0006)"
                )

    def risk_of(self, capability: str) -> str:
        entry = self.capabilities.get(capability)
        if not entry:
            return self.fallback_risk
        risk = entry.get("action_risk", self.fallback_risk)
        return risk if risk in RISK_ORDER else self.fallback_risk

    def _floor_for(self, capability: str, risk: str) -> str | None:
        floors = [
            required
            for pattern, required in self.floor_capabilities.items()
            if fnmatch.fnmatch(capability, pattern)
        ]
        if risk in self.floor_risk:
            floors.append(self.floor_risk[risk])
        if not floors:
            return None
        return max(floors, key=lambda a: _rank(a, AUTHORITY_ORDER))

    def evaluate(self, capability: str, *, tenant_overrides: dict | None = None) -> Decision:
        risk = self.risk_of(capability)
        entry = self.capabilities.get(capability) or {}

        authority = (tenant_overrides or {}).get(risk) or self.authority_map.get(risk)
        if authority not in AUTHORITY_ORDER:
            authority = self.fallback_authority

        reason = f"capability '{capability}' risk={risk}"

        override = entry.get("override_authority")
        if override in AUTHORITY_ORDER:
            authority = override
            reason += f" · override เฉพาะ capability นี้ ({override})"

        audited_exception = bool(override in AUTHORITY_ORDER and entry.get("requires_full_audit"))
        floor = self._floor_for(capability, risk)
        if floor and _rank(authority, AUTHORITY_ORDER) < _rank(floor, AUTHORITY_ORDER):
            if audited_exception:
                reason += " · ข้อยกเว้นที่ต้อง audit เต็ม"
            else:
                authority = floor
                reason += f" · ยกขึ้นตามเพดาน {floor}"

        return Decision(
            effect="allow",
            authority=authority,
            action_risk=risk,
            policy_id=self.policy_id,
            capability=capability,
            reason=reason,
            evaluated_at=now(),
            audited_exception=audited_exception,
        )


def evaluate(
    capability: str,
    *,
    tenant_overrides: dict | None = None,
    path: str | None = None,
    actor_type: str | None = None,
) -> Decision:
    """ตัดสิน capability นี้ — แล้วเอาผลไปผ่าน **เพดานของ profile** อีกชั้น

    `actor_type` คือชนิดของ principal ที่กำลังจะลงมือ · profile เป็นเพดานของ **agent**
    ไม่ใช่ของคน — ผู้ดูแลที่ยืนยันคำสั่งยาคือการใช้อำนาจของคน ไม่ใช่การที่ agent ทำงาน
    """
    decision = load_policy(path).evaluate(capability, tenant_overrides=tenant_overrides)
    return apply_profile(decision, actor_type=actor_type)


def apply_profile(decision: Decision, *, actor_type: str | None = None) -> Decision:
    """🔒 ค่าที่กว้างที่สุดชนะไม่ได้ — ผลลัพธ์คือส่วนที่ profile กับ policy ตกลงตรงกัน"""
    from care_addons.ap_policy.profile import load_profile

    profile = load_profile()
    capability = decision.capability
    authority = decision.authority
    effect = decision.effect
    reason = decision.reason
    denied = False

    # require_human_for ยกพื้นเหนือ authority_map — ใช้กับทุก actor ไม่ใช่แค่ agent
    if profile.requires_human(capability) and _rank(authority, AUTHORITY_ORDER) < _rank(
        "human_command_required", AUTHORITY_ORDER
    ):
        authority = "human_command_required"
        reason += " · profile บังคับว่าต้องให้คนสั่ง"

    # ข้อยกเว้นที่ประกาศไว้อย่างเปิดเผยและต้อง audit เต็ม ไม่ถูกเพดานยกทับ
    # (ไม่งั้น emergency.escalate จะกลายเป็น human_command_required ซึ่งแปลว่า
    #  ตอนฉุกเฉินระบบจะรอคนสั่งก่อนถึงจะเรียกคน — ตรงข้ามกับที่ต้องการ)
    ceiling = None if decision.audited_exception else profile.ceiling_for(decision.action_risk)
    if ceiling and _rank(authority, AUTHORITY_ORDER) < _rank(ceiling, AUTHORITY_ORDER):
        authority = ceiling
        reason += f" · ยกขึ้นตามเพดานของ profile ({ceiling})"

    if profile.governs(actor_type):
        if profile.denies(capability):
            denied, effect = True, "deny"
            authority = "human_command_required"
            reason += f" · profile '{profile.profile_id}' ห้าม agent ใช้ capability นี้"
        elif not profile.allows(capability):
            # allow ว่าง/ไม่ครอบ = ไม่อนุญาต ไม่ใช่ "อนุญาตทั้งหมด" (profile/v1)
            denied, effect = True, "deny"
            authority = "human_command_required"
            reason += f" · capability นี้ไม่อยู่ใน allowlist ของ profile '{profile.profile_id}'"

    if (effect, authority, denied) == (decision.effect, decision.authority, decision.profile_denied):
        return decision
    return replace(decision, effect=effect, authority=authority, reason=reason, profile_denied=denied)


def require_autonomy(capability: str, *, tenant_overrides: dict | None = None) -> Decision:
    """ใช้เมื่อ agent จะลงมือเอง — authority ที่ต้องมีคนเกี่ยวข้องจะ raise ทันที"""
    decision = evaluate(capability, tenant_overrides=tenant_overrides)
    if not decision.may_act_now:
        raise PolicyDenied(decision)
    return decision
