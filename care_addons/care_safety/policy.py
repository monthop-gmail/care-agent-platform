"""อ่านกติกาความปลอดภัยจาก policies/escalation-policy.yaml — ไม่ hardcode ในโค้ด

เกณฑ์ความมั่นใจและหน้าต่างรวมสัญญาณเป็นเรื่องของแต่ละบ้านและแต่ละอุปกรณ์
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / "policies" / "escalation-policy.yaml"

FALLBACK_MIN_CONFIDENCE = 0.7
FALLBACK_DEDUP_MINUTES = 15
# 🔒 ชนิดที่ config ไม่ได้พูดถึง → medium ไม่ใช่ low
#    สัญญาณที่เราไม่รู้จักต้องไม่เงียบกว่าที่ควร (fail closed เหมือน ap_policy)
FALLBACK_SEVERITY = "medium"


class SafetyPolicy:
    def __init__(self, config: dict) -> None:
        block = config.get("safety") or {}
        self.min_confidence: float = float(
            block.get("min_confidence_to_escalate", FALLBACK_MIN_CONFIDENCE)
        )
        self.dedup_window_minutes: int = int(
            block.get("dedup_window_minutes", FALLBACK_DEDUP_MINUTES)
        )
        self.severity_by_kind: dict = block.get("severity_by_kind") or {}

    def severity_for(self, kind: str) -> str:
        return self.severity_by_kind.get(kind, FALLBACK_SEVERITY)

    def may_escalate(self, confidence: float | None) -> bool:
        """ไม่ส่ง confidence มา = อุปกรณ์ไม่ได้บอก → ถือว่าเชื่อได้ตามที่แจ้ง

        เหตุผล: อุปกรณ์จำนวนมากไม่มีค่านี้เลย (door sensor เปิดคือเปิด) การตีความ
        "ไม่มีค่า" ว่า "มั่นใจต่ำ" จะทำให้สัญญาณจริงถูกกลืนหายทั้งหมด
        """
        if confidence is None:
            return True
        return confidence >= self.min_confidence


@lru_cache(maxsize=4)
def load(path: str | None = None) -> SafetyPolicy:
    import yaml

    data = yaml.safe_load(Path(path or POLICY_PATH).read_text(encoding="utf-8")) or {}
    return SafetyPolicy(data)
