"""กฎสถาปัตยกรรมที่ต้องบังคับด้วยเทส ไม่ใช่ด้วยการรีวิวอย่างเดียว

ADR-0003 กฎ 4 ข้อของ `ap_*` และ ADR-0006 เรื่องการประกาศ action_risk
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADDONS = ROOT / "care_addons"
AP_MODULES = sorted(p.name for p in ADDONS.iterdir() if p.is_dir() and p.name.startswith("ap_"))
CARE_MODULES = sorted(p.name for p in ADDONS.iterdir() if p.is_dir() and p.name.startswith("care_"))

DOMAIN_WORDS = ["patient", "medication", "caregiver", "appointment", "journal", "routine"]


def _python_files(module: str):
    return [p for p in (ADDONS / module).rglob("*.py")]


def test_ap_layer_does_not_import_domain_modules():
    """ADR-0003 กฎ 1 — `ap_*` ห้ามพึ่ง `care_*` ไม่งั้น promote ขึ้น pstack ไม่ได้"""
    offenders = []
    for module in AP_MODULES:
        for path in _python_files(module):
            for line in path.read_text(encoding="utf-8").splitlines():
                if re.match(r"\s*(from|import)\s+care_addons\.care_", line):
                    offenders.append(f"{path.relative_to(ROOT)}: {line.strip()}")
    assert not offenders, "ap_* import จาก care_* ไม่ได้:\n" + "\n".join(offenders)


def test_ap_layer_has_no_domain_vocabulary_in_models():
    """ap_* ต้องไม่รู้จักคำของโดเมน — สิ่งที่ถูกคุ้มครองเรียกว่า subject เท่านั้น"""
    offenders = []
    for module in AP_MODULES:
        for path in _python_files(module):
            if path.name not in ("models.py", "services.py", "engine.py"):
                continue
            text = path.read_text(encoding="utf-8").lower()
            # ตัดคอมเมนต์ออกก่อน — ห้ามเฉพาะการใช้คำเหล่านี้เป็นโครงสร้างข้อมูล
            code = "\n".join(
                line.split("#")[0] for line in text.splitlines() if not line.strip().startswith("#")
            )
            code = re.sub(r'""".*?"""', "", code, flags=re.DOTALL)
            for word in DOMAIN_WORDS:
                if word in code:
                    offenders.append(f"{path.relative_to(ROOT)}: พบคำว่า '{word}'")
    assert not offenders, "ap_* ห้ามรู้จักคำของโดเมน (ADR-0003 กฎ 1):\n" + "\n".join(offenders)


def test_ap_manifests_depend_only_on_users_and_ap():
    """ADR-0003 กฎ 2"""
    import ast

    for module in AP_MODULES:
        manifest = ast.literal_eval((ADDONS / module / "__manifest__.py").read_text(encoding="utf-8"))
        for dependency in manifest.get("depends", []):
            assert dependency == "users" or dependency.startswith("ap_"), (
                f"{module} depends on '{dependency}' — ap_* พึ่งได้แค่ users ของ pstack กับ ap_* ด้วยกัน"
            )


def test_ap_tables_and_routes_are_namespaced():
    """ADR-0003 กฎ 3 — ตารางขึ้นต้น ap_ และ route อยู่ใต้ /api/platform"""
    for module in AP_MODULES:
        models = ADDONS / module / "models.py"
        if models.exists():
            for table in re.findall(r'__tablename__\s*=\s*"([^"]+)"', models.read_text(encoding="utf-8")):
                assert table.startswith("ap_"), f"{module}: ตาราง '{table}' ต้องขึ้นต้นด้วย ap_"
        routes = ADDONS / module / "routes.py"
        if routes.exists():
            for prefix in re.findall(r'prefix="([^"]+)"', routes.read_text(encoding="utf-8")):
                assert prefix.startswith("/api/platform"), (
                    f"{module}: route prefix '{prefix}' ต้องอยู่ใต้ /api/platform"
                )


def test_care_modules_depend_on_the_conformance_layer():
    """ทุก addon โดเมนต้องผ่าน tenancy/audit/policy — ไม่มีข้อยกเว้น (team-plan)"""
    import ast

    required = {"ap_tenancy", "ap_audit", "ap_policy"}
    for module in CARE_MODULES:
        manifest = ast.literal_eval((ADDONS / module / "__manifest__.py").read_text(encoding="utf-8"))
        missing = required - set(manifest.get("depends", []))
        assert not missing, f"{module} ขาด depends: {sorted(missing)}"


def test_every_declared_action_has_a_risk_in_policy_config():
    """ADR-0006 — action ที่ไม่ได้ประกาศ risk จะได้ critical (fail closed)

    fail closed ทำให้ระบบปลอดภัยแต่ทำงานไม่ได้ ดังนั้น capability ที่ใช้จริง
    ต้องอยู่ใน policies/care-authority-map.yaml ไม่ใช่ตกไปที่ค่า fallback โดยไม่ตั้งใจ
    """
    import care_addons.care_journal.services
    import care_addons.care_medication.services
    import care_addons.care_patient.services  # noqa: F401
    from care_addons.ap_policy.engine import load_policy
    from care_addons.ap_policy.services import DECLARED

    policy = load_policy()
    missing = [c for c in DECLARED if c not in policy.capabilities]
    assert not missing, (
        "capability ที่ประกาศในโค้ดแต่ไม่มีใน policies/care-authority-map.yaml "
        f"(จะตกไปที่ critical/human_command_required โดยไม่ตั้งใจ): {missing}"
    )


def test_no_direct_datetime_now_in_domain_code():
    """เวลาต้องมาจาก ap_tenancy.clock เท่านั้น ไม่งั้น scenario test เลื่อนเวลาไม่ได้"""
    offenders = []
    for module in AP_MODULES + CARE_MODULES:
        for path in _python_files(module):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "datetime.now(" in line and "clock.py" not in path.name:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert not offenders, "ใช้ clock.now() แทน datetime.now():\n" + "\n".join(offenders)


def test_dockerfile_copies_every_runtime_directory():
    """โค้ดอ่าน policies/ ตอน runtime — ถ้า image ไม่มี ระบบจะพังตอนมีงานเข้า ไม่ใช่ตอน boot

    บั๊กนี้เคยเกิดจริง: เทสบนเครื่องผ่านหมดเพราะอ่านจาก repo แต่ใน container ไม่มีไฟล์
    """
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for directory in ("care_addons", "policies", "profiles"):
        assert f"COPY {directory} " in dockerfile, (
            f"Dockerfile ไม่ได้ copy '{directory}/' เข้า image "
            f"— โค้ดที่อ่านไฟล์ในโฟลเดอร์นี้จะพังใน container"
        )


def test_care_tick_is_registered_as_a_periodic_job():
    """closed loop ต้องมีอะไรมาปลุก — ถ้า care_tick กลับไปเป็น @background_job เฉย ๆ
    ระบบจะเงียบสนิทโดยไม่มี error ใด ๆ ซึ่งแปลว่าไม่มีใครเตือนผู้ป่วยและไม่มีใครรู้

    ต้องการ pstack >= v0.2.0 (willpower-institute/pstack#2)
    """
    from core.jobs import _periodic  # kernel ยังไม่มี public accessor — ดู pstack#2

    import care_addons.care_escalation.jobs  # noqa: F401  ลงทะเบียนตอน import

    assert "care_tick" in [fn.__name__ for fn, _ in _periodic]
