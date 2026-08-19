"""อ่านเวลาส่งสรุปจาก policies/escalation-policy.yaml — ไม่ hardcode ไว้ในโค้ด

เวลาส่งเป็นเรื่องของครอบครัว ไม่ใช่ของโปรแกรมเมอร์ · ที่นี่แค่อ่านค่าที่ตั้งไว้
"""

from __future__ import annotations

from datetime import time
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "policies" / "escalation-policy.yaml"
FALLBACK_SEND_AT = time(20, 0)


@lru_cache(maxsize=4)
def _config(path: str | None = None) -> dict:
    import yaml

    data = yaml.safe_load(Path(path or DEFAULT_PATH).read_text(encoding="utf-8")) or {}
    return data.get("daily_summary") or {}


def send_at(path: str | None = None) -> time:
    raw = _config(path).get("send_at")
    if not isinstance(raw, str):
        return FALLBACK_SEND_AT
    hh, _, mm = raw.partition(":")
    try:
        return time(int(hh), int(mm or 0))
    except ValueError:
        return FALLBACK_SEND_AT


def include(path: str | None = None) -> list[str]:
    return list(_config(path).get("include") or [])
