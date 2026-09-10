#!/usr/bin/env python3
"""ตรวจว่า **เพดานของ agent มีผลบังคับจริง** ไม่ใช่ไฟล์ที่วางอยู่เฉย ๆ

ทำไมต้องมี: `profiles/care-agent/profile.yaml` เคยอยู่ใน git ครบถ้วนหนึ่งเดือน
โดย **ไม่มีโค้ดบรรทัดไหนอ่านมันเลย** และชื่อ capability ในไฟล์ก็เป็นชื่อที่ไม่มีอยู่จริง
(`care.medication.write_regimen` ขณะที่ของจริงคือ `medication.regimen.write`)

    เพดานที่สะกดชื่อผิดคือเพดานที่ไม่มีอยู่ และอันตรายกว่าไม่มีเพดานเลย
    เพราะคนอ่านไฟล์แล้วเชื่อว่าระบบกันให้อยู่

`drift_check` ตรวจไม่ได้ เพราะมันดูว่า contract ของเรา `$ref` ถูกที่ ไม่ได้ดูว่าเพดาน
ถูกบังคับ · `payload_check` ก็ตรวจไม่ได้ เพราะมัน validate payload ที่ระบบผลิต
ไม่ได้ตรวจสิ่งที่ระบบ **ปฏิเสธ** · สคริปต์นี้ปิดช่องนั้น

ประกาศไว้ใน `platform-contract.yaml` เพื่อให้ทีมอื่นตรวจได้เองว่าเพดานของเราถูกบังคับจริง
โดยไม่ต้องเชื่อรายงานของเรา — เกณฑ์เดียวกับที่ใช้กับ evidence ทุกชิ้น
(agent-platform ถามข้อนี้ตรง ๆ ที่ ai-collab dis-65134078 seq 16)

รัน:
    python conformance/profile_check.py

🔒 **อ่านอย่างเดียว ไม่แตะฐานข้อมูล** — รันกับ deployment จริงได้ปลอดภัย
   ต่างจาก migration/payload/rls check ที่เริ่มด้วย DROP SCHEMA (ดู conformance/_guard.py)
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for candidate in (ROOT / "pstack_src", ROOT.parent / "pstack"):
    if (candidate / "addons").is_dir():
        os.environ.setdefault("PSTACK_ADDONS_PATHS", f"{candidate / 'addons'},care_addons")
        sys.path.insert(0, str(candidate))
        break

# โมดูลโดเมนที่ประกาศ capability ด้วย @care_action — import เพื่อให้ DECLARED ครบ
# (ไม่ได้บูตแอปและไม่ต่อ DB — แค่ import ให้ decorator ทำงาน)
DOMAIN_MODULES = [
    "care_patient", "care_escalation", "care_routine", "care_medication",
    "care_journal", "care_appointment", "care_orientation", "care_careplan",
    "care_activity", "care_inventory", "care_home", "care_safety",
    "care_organization", "care_orchestrator",
]


def main() -> int:
    import importlib

    for module in DOMAIN_MODULES:
        importlib.import_module(f"care_addons.{module}.services")

    from care_addons.ap_policy.engine import AUTHORITY_ORDER, evaluate, load_policy
    from care_addons.ap_policy.profile import load_profile
    from care_addons.ap_policy.services import DECLARED

    policy = load_policy()
    profile = load_profile()
    failures: list[str] = []

    # (1) ทุกชื่อใน allow ต้องเป็น capability ที่ประกาศไว้จริงใน policy config
    #     ข้อนี้คือข้อที่เราพลาดมาก่อน — ชื่อที่ไม่มีอยู่จริงทำให้เพดานเป็น no-op
    unknown = [c for c in profile.allow if c not in policy.capabilities]
    failures += [f"tools.allow มีชื่อที่ไม่มีใน policy config: {c}" for c in unknown]

    # (2) deny ที่ตรงกับ capability จริง ต้องถูกปฏิเสธจริงเมื่อผู้กระทำเป็น agent
    #     ตรวจด้วยการ "ถามเครื่อง" ไม่ใช่การอ่านไฟล์ — ไฟล์อาจถูกอ่านผิดหรือไม่ถูกอ่านเลย
    for capability in policy.capabilities:
        if not profile.denies(capability):
            continue
        decision = evaluate(capability, actor_type="agent")
        if not decision.profile_denied or decision.may_act_now:
            failures.append(
                f"'{capability}' อยู่ใน tools.deny แต่ evaluate() ยังปล่อยให้ agent เดินต่อได้"
            )

    # (3) capability ที่ประกาศไว้แต่ไม่อยู่ใน allow ต้องถูกปฏิเสธสำหรับ agent
    #     (allow เป็นชุดปิด — ไม่อยู่ในนั้นคือไม่อนุญาต ไม่ใช่ "อนุญาตทั้งหมด")
    for capability in DECLARED:
        if profile.allows(capability) or capability not in policy.capabilities:
            continue
        decision = evaluate(capability, actor_type="agent")
        if not decision.profile_denied:
            failures.append(
                f"'{capability}' ไม่อยู่ใน tools.allow แต่ agent ยังเรียกได้ — allow ไม่ได้เป็นชุดปิด"
            )

    # (4) action ที่ประกาศว่า autonomous=False ต้องไม่ถูกปล่อยให้ agent เรียกเอง
    leaked = [
        capability
        for capability, meta in DECLARED.items()
        if not meta["autonomous"] and not evaluate(capability, actor_type="agent").profile_denied
    ]
    failures += [f"action ที่ต้องมีคนสั่ง แต่ agent เรียกได้: {c}" for c in leaked]

    # (5) authority_map ของ tenant ต้องไม่หลวมกว่าเพดานของ profile
    #     (`load_policy()` raise เองตั้งแต่ boot — ตรงนี้ยืนยันว่ากลไกนั้นยังอยู่)
    for risk, ceiling in profile.authority_map.items():
        configured = policy.authority_map.get(risk)
        if not configured:
            continue
        if AUTHORITY_ORDER.index(configured) < AUTHORITY_ORDER.index(ceiling):
            failures.append(
                f"authority_map[{risk}]={configured} หลวมกว่าเพดานของ profile ({ceiling})"
            )

    # (6) คนไม่ได้อยู่ใต้เพดานของ agent — ถ้าเพดานกินคนด้วย ผู้ดูแลจะทำงานของตัวเองไม่ได้
    for capability in profile.deny:
        if capability not in policy.capabilities:
            continue
        if evaluate(capability, actor_type="human").profile_denied:
            failures.append(
                f"'{capability}' ถูกปฏิเสธสำหรับ 'human' ด้วย — เพดานของ agent ไม่ควรกินคน"
            )

    for failure in failures[:30]:
        print(f"   {failure}")
    if failures:
        print(f"\n✗ เพดานของ agent ไม่ผ่าน — {len(failures)} ข้อ")
        return 1

    print(
        f"✓ เพดานของ agent บังคับจริง — profile '{profile.profile_id}' "
        f"อนุญาต {len(profile.allow)} ห้าม {len(profile.deny)} · "
        f"ตรวจกับ {len(policy.capabilities)} capability ที่ประกาศไว้ "
        f"({len(DECLARED)} ตัวมี @care_action)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
