"""อ่าน policies/escalation-policy.yaml — กติกาการเตือนซ้ำและการส่งต่อ"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / "policies" / "escalation-policy.yaml"


@dataclass(frozen=True)
class EscalationPolicy:
    policy_id: str = "care.escalation.v1"
    max_attempts: int = 3
    backoff_minutes: tuple[int, ...] = (10, 20)
    ask_directly_on_attempt: int = 3
    quiet_hours_severities: tuple[str, ...] = ("low", "medium", "high")
    wait_between_targets_minutes: int = 15
    stop_on_acknowledged: bool = True
    aggregation_window_minutes: int = 30
    by_severity: dict = field(default_factory=dict)

    def backoff_for(self, attempt: int) -> int:
        """attempt เริ่มที่ 1 — ถ้าเกินรายการที่กำหนด ใช้ค่าสุดท้าย"""
        if not self.backoff_minutes:
            return 10
        index = min(max(attempt - 1, 0), len(self.backoff_minutes) - 1)
        return self.backoff_minutes[index]

    def notifies_caregiver(self, severity: str) -> bool:
        return bool((self.by_severity.get(severity) or {}).get("notify_caregiver", severity != "low"))

    def notifies_immediately(self, severity: str) -> bool:
        rules = self.by_severity.get(severity) or {}
        return bool(rules.get("immediately") or rules.get("notify_all"))

    def notifies_all_targets(self, severity: str) -> bool:
        return bool((self.by_severity.get(severity) or {}).get("notify_all", False))

    def respects_quiet_hours(self, severity: str) -> bool:
        return severity in self.quiet_hours_severities


@lru_cache(maxsize=4)
def load(path: str | None = None) -> EscalationPolicy:
    import yaml

    raw = yaml.safe_load(Path(path or POLICY_PATH).read_text(encoding="utf-8")) or {}
    reminder = raw.get("reminder") or {}
    quiet = raw.get("quiet_hours") or {}
    escalation = raw.get("escalation") or {}
    aggregation = raw.get("aggregation") or {}
    return EscalationPolicy(
        policy_id=raw.get("policy_id", "care.escalation.v1"),
        max_attempts=int(reminder.get("max_attempts", 3)),
        backoff_minutes=tuple(reminder.get("backoff_minutes") or (10, 20)),
        ask_directly_on_attempt=int(reminder.get("ask_directly_on_attempt", 3)),
        quiet_hours_severities=tuple(quiet.get("respect_for_severity") or ("low", "medium", "high")),
        wait_between_targets_minutes=int(escalation.get("wait_between_targets_minutes", 15)),
        stop_on_acknowledged=bool(escalation.get("stop_on_acknowledged", True)),
        aggregation_window_minutes=int(aggregation.get("window_minutes", 30)),
        by_severity=escalation.get("by_severity") or {},
    )
