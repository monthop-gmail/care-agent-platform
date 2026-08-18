#!/usr/bin/env python3
"""ตรวจว่า contract ของ repo นี้ยังยึดกับ agent-platform เวอร์ชันที่ pin ไว้

ตรวจ 4 อย่าง:
  1. ทุก $ref ที่ชี้ไป agent-platform ต้องอยู่ใน allowed_refs ของ conformance/pinned.yaml
  2. ทุก $ref ที่ชี้ไปในโดเมนตัวเอง ต้องมีไฟล์และ pointer อยู่จริง
  3. ห้ามนิยาม $defs ที่ agent-platform นิยามไว้แล้วซ้ำ (ADR-0001)
  4. --online: ดึง contract จาก commit ที่ pin แล้วยืนยันว่า pointer มีจริง

รัน:
    python conformance/drift_check.py            # offline (ใช้ใน CI ปกติ)
    python conformance/drift_check.py --online   # ตรวจกับ GitHub ที่ commit ที่ pin
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
PINNED = Path(__file__).resolve().parent / "pinned.yaml"

PLATFORM_HOST = "schemas.agent-platform.internal"
DOMAIN_HOST = "schemas.care-agent-platform.internal"
RAW = "https://raw.githubusercontent.com/{repo}/{commit}/contracts/{path}"

# $defs ที่เป็นของ agent-platform — นิยามซ้ำที่นี่ไม่ได้ (ADR-0001)
PLATFORM_OWNED_DEFS = {
    "Id", "TenantId", "WorkspaceId", "ActorId", "AgentId", "ExecutionId",
    "Principal", "RequestContext", "ExecutionContext",
    "Effect", "Authority", "Constraint", "ActionRisk",
    "EventType", "SubjectType",
}

REF_RE = re.compile(r"\$ref:\s*'?\"?(?P<ref>https://[^\s'\"]+|#/[^\s'\"]+)'?\"?")
DEFS_RE = re.compile(r"^\$defs:\s*$", re.MULTILINE)

errors: list[str] = []
warnings: list[str] = []


def load_pinned() -> dict:
    """อ่าน pinned.yaml — ใช้ yaml ถ้ามี ไม่มีก็ parse เท่าที่ต้องใช้ (kernel ไม่บังคับ dep)"""
    text = PINNED.read_text(encoding="utf-8")
    try:
        import yaml

        return yaml.safe_load(text)
    except ImportError:
        data: dict = {"allowed_refs": {}}
        current: str | None = None
        in_allowed = False
        for line in text.splitlines():
            if line.startswith("allowed_refs:"):
                in_allowed = True
                continue
            if in_allowed and line and not line[0].isspace():
                in_allowed = False
            if not in_allowed:
                if ":" in line and not line.startswith((" ", "#")):
                    k, _, v = line.partition(":")
                    data[k.strip()] = v.strip().strip('"')
                continue
            if re.match(r"^  \S", line):
                current = line.strip().rstrip(":")
                data["allowed_refs"][current] = []
            elif line.strip().startswith("- ") and current:
                data["allowed_refs"][current].append(line.strip()[2:].strip().strip('"'))
        return data


def split_ref(ref: str) -> tuple[str, str, str]:
    """คืน (host, path, pointer)"""
    body, _, pointer = ref.partition("#")
    pointer = pointer.lstrip("/")
    m = re.match(r"https://([^/]+)/(.+)", body)
    if not m:
        return ("", body, pointer)
    return (m.group(1), m.group(2), pointer)


def check_file(path: Path, pinned: dict) -> None:
    rel = path.relative_to(ROOT)
    text = path.read_text(encoding="utf-8")
    allowed = pinned.get("allowed_refs") or {}

    for m in REF_RE.finditer(text):
        ref = m.group("ref")
        if ref.startswith("#/"):
            pointer = ref[2:]
            if pointer not in text.replace("$defs:", "$defs:"):
                pass  # local pointer — ตรวจแบบหยาบด้านล่าง
            name = pointer.split("/")[-1]
            if f"  {name}:" not in text:
                errors.append(f"{rel}: local $ref '{ref}' ไม่มี $defs ชื่อ '{name}' ในไฟล์เดียวกัน")
            continue

        host, apath, pointer = split_ref(ref)

        if host == PLATFORM_HOST:
            if apath not in allowed:
                errors.append(
                    f"{rel}: $ref ไปที่ '{apath}' ซึ่งไม่อยู่ใน allowed_refs "
                    f"— เพิ่มใน conformance/pinned.yaml ก่อน"
                )
                continue
            entries = allowed[apath] or []
            key = pointer if pointer else ""
            if key not in entries:
                errors.append(
                    f"{rel}: $ref '{apath}#{pointer}' ไม่อยู่ใน allowed_refs ของไฟล์นั้น "
                    f"(มี: {', '.join(e or '(ทั้งไฟล์)' for e in entries)})"
                )
        elif host == DOMAIN_HOST:
            target = CONTRACTS / apath
            if not target.exists():
                errors.append(f"{rel}: $ref ไปที่ contract ในโดเมนที่ไม่มีอยู่จริง: {apath}")
                continue
            if pointer:
                name = pointer.split("/")[-1]
                if f"  {name}:" not in target.read_text(encoding="utf-8"):
                    errors.append(f"{rel}: $ref '{apath}#{pointer}' — ไม่พบ '{name}' ในไฟล์ปลายทาง")
        else:
            warnings.append(f"{rel}: $ref ไปที่ host ที่ไม่รู้จัก: {host or ref}")

    # ห้ามนิยาม $defs ที่เป็นของ platform ซ้ำ
    for m in re.finditer(r"^  (\w+):$", text, re.MULTILINE):
        name = m.group(1)
        if name in PLATFORM_OWNED_DEFS:
            errors.append(
                f"{rel}: นิยาม $defs '{name}' ซ้ำกับ agent-platform "
                f"— ต้อง $ref ไปที่ต้นทางแทน (ADR-0001)"
            )


def check_online(pinned: dict) -> None:
    import urllib.request

    repo = pinned.get("repo", "monthop-gmail/agent-platform")
    commit = pinned.get("commit", "")
    if not commit:
        errors.append("pinned.yaml: ไม่มี commit ที่ pin")
        return
    for apath, pointers in (pinned.get("allowed_refs") or {}).items():
        url = RAW.format(repo=repo, commit=commit, path=apath)
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                body = r.read().decode("utf-8")
        except Exception as e:  # pragma: no cover - เครือข่ายล่ม
            errors.append(f"online: ดึง {apath} ที่ commit {commit[:8]} ไม่ได้ ({e})")
            continue
        for pointer in pointers or []:
            if not pointer:
                continue
            name = pointer.split("/")[-1]
            if f"  {name}:" not in body:
                errors.append(
                    f"online: {apath}#{pointer} ไม่มีที่ commit {commit[:8]} แล้ว — contract drift"
                )


def main() -> int:
    online = "--online" in sys.argv
    pinned = load_pinned()

    files = sorted(CONTRACTS.rglob("*.yaml"))
    if not files:
        print("ไม่พบ contract ใน contracts/ — ข้าม")
        return 0

    for path in files:
        check_file(path, pinned)

    if online:
        check_online(pinned)

    for w in warnings:
        print(f"warn: {w}")
    for e in errors:
        print(f"DRIFT: {e}")

    scope = "online" if online else "offline"
    if errors:
        print(f"\n✗ drift check ({scope}) ไม่ผ่าน — {len(errors)} ข้อ · ตรวจ {len(files)} ไฟล์")
        return 1
    print(f"✓ drift check ({scope}) ผ่าน — {len(files)} ไฟล์ · pin ที่ {pinned.get('commit', '?')[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
