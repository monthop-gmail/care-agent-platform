"""กฎสถาปัตยกรรมที่ต้องบังคับด้วยเทส ไม่ใช่ด้วยการรีวิวอย่างเดียว

ADR-0003 กฎ 4 ข้อของ `ap_*` และ ADR-0006 เรื่องการประกาศ action_risk
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

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


# โมดูลของ kernel ที่ `ap_*` พึ่งได้ — ต้องเป็นของ pstack เท่านั้น ห้ามมี care_* หลุดเข้ามา
KERNEL_MODULES = {"users", "tenancy"}


def test_ap_manifests_depend_only_on_kernel_and_ap():
    """ADR-0003 กฎ 2 — `ap_*` พึ่ง kernel ของ pstack กับ `ap_*` ด้วยกันเท่านั้น

    เดิมกฎเขียนว่า "users + ap_*" ตอนที่ kernel ยังไม่มี tenancy — พอ tenancy ขึ้น kernel
    (pstack v0.3.0) `ap_*` พึ่ง `tenancy` ได้ เพราะเจตนาของกฎคือ **ห้ามพึ่งโดเมน**
    ไม่ใช่ห้ามพึ่ง kernel
    """
    import ast

    for module in AP_MODULES:
        manifest = ast.literal_eval((ADDONS / module / "__manifest__.py").read_text(encoding="utf-8"))
        for dependency in manifest.get("depends", []):
            assert dependency in KERNEL_MODULES or dependency.startswith("ap_"), (
                f"{module} depends on '{dependency}' — ap_* พึ่งได้แค่ kernel ของ pstack "
                f"({', '.join(sorted(KERNEL_MODULES))}) กับ ap_* ด้วยกัน"
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

    # `tenancy` เป็นโมดูลของ kernel ตั้งแต่ pstack v0.3.0 — shim `ap_tenancy` ถูกลบแล้ว (ADR-0003 รอบ 2)
    required = {"tenancy", "ap_audit", "ap_policy"}
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
    """เวลาต้องมาจาก `core.clock` เท่านั้น ไม่งั้น scenario test เลื่อนเวลาไม่ได้"""
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

    ต้องการ pstack >= v0.2.2 (willpower-institute/pstack#2, #8)
    """
    from core.jobs import periodic_jobs

    import care_addons.care_escalation.jobs  # noqa: F401  ลงทะเบียนตอน import

    assert "care_tick" in [fn.__name__ for fn, _ in periodic_jobs()]


def test_daily_tick_is_registered_as_a_periodic_job():
    """สรุปประจำวันต้องมีอะไรมาปลุกเหมือน care_tick — ไม่งั้นผู้ดูแลจะไม่ได้อะไรเลยโดยไม่มี error"""
    from core.jobs import periodic_jobs

    import care_addons.care_orchestrator.jobs  # noqa: F401  ลงทะเบียนตอน import

    assert "care_daily_tick" in [fn.__name__ for fn, _ in periodic_jobs()]


def test_every_session_opened_in_addons_binds_a_tenant():
    """ทุกที่ที่เปิด session เองต้องผูก tenant ก่อนแตะข้อมูลโดเมน

    RLS ปฏิเสธแบบ deny-by-default — ลืมผูกแล้วจะ **เห็น 0 แถวโดยไม่มี error**
    ซึ่งแปลว่า worker เตือนผู้ป่วยเงียบ ๆ โดยไม่มีใครรู้ (care-agent-platform#4)

    request ที่มาทาง HTTP ไม่ต้องทำเอง — `get_scope` ของ kernel ผูกให้แล้ว
    (ตั้งแต่ pstack v0.3.1 `bind_tenant` เป็นของ kernel — เดิมเราเขียนเองแล้วเสนอขึ้นไป)
    """
    # ยกเว้นได้เฉพาะไฟล์ที่เปิด session ไปอ่านตารางที่ **ไม่มี tenant_id** เท่านั้น
    # เพิ่มรายการที่นี่ต้องเขียนเหตุผลกำกับ และต้องผ่านสายตาคนรีวิว
    ALLOWED = {
        # อ่าน access_token ของ LINE channel (ตารางของ pstack ไม่มี tenant_id ไม่มี RLS)
        "care_addons/care_line/services.py",
    }

    offenders = []
    for module in AP_MODULES + CARE_MODULES:
        for path in _python_files(module):
            relative = str(path.relative_to(ROOT))
            text = path.read_text(encoding="utf-8")
            if "get_sessionmaker()(" not in text or relative in ALLOWED:
                continue
            if "bind_tenant" not in text:
                offenders.append(relative)
    assert not offenders, (
        "ไฟล์ที่เปิด session เองแต่ไม่ได้ผูก tenant — RLS จะให้ 0 แถวเงียบ ๆ:\n"
        + "\n".join(offenders)
    )


def test_pstack_ref_is_the_same_everywhere():
    """`PSTACK_REF` ต้องตรงกันทั้ง 3 ที่ — .env.example · Dockerfile ARG · compose default

    ทั้งสามที่ต่างคนต่างมีค่า default ของตัวเอง ถ้าปล่อยให้ drift:
    - `docker build .` (ไม่ส่ง --build-arg) จะได้ image ที่ pin kernel คนละเวอร์ชันกับที่เทสไว้
    - เจอจริง: merge PR ที่ bump เป็น v0.3.1 แต่ Dockerfile ยังค้าง v0.3.0 ซึ่งไม่มี
      `core.tenancy.bind_tenant` ที่โค้ดเราใช้ 7 จุด → image พังตั้งแต่ import
      (`ImportError: cannot import name 'bind_tenant'`) โดย CI ไม่จับเพราะ compose ส่งค่าทับให้
    """
    import re

    env = re.search(r"^PSTACK_REF=(\S+)", (ROOT / ".env.example").read_text(encoding="utf-8"), re.MULTILINE)
    dockerfile = re.search(
        r"^ARG PSTACK_REF=(\S+)", (ROOT / "Dockerfile").read_text(encoding="utf-8"), re.MULTILINE
    )
    compose = re.findall(
        r"PSTACK_REF:\s*\$\{PSTACK_REF:-([^}]+)\}",
        (ROOT / "docker-compose.yml").read_text(encoding="utf-8"),
    )

    assert env and dockerfile and compose, "หา PSTACK_REF ไม่ครบทั้งสามที่"
    refs = {".env.example": env.group(1), "Dockerfile": dockerfile.group(1)}
    for index, value in enumerate(compose):
        refs[f"docker-compose[{index}]"] = value

    assert len(set(refs.values())) == 1, f"PSTACK_REF ไม่ตรงกัน: {refs}"


def test_profile_allowlist_uses_real_capability_names():
    """ชื่อใน profile ต้องเป็น capability จริง — ไม่งั้นไฟล์กลายเป็นเอกสารที่ไม่มีผล

    เพดานที่สะกดชื่อผิดคือเพดานที่ไม่มีอยู่ และอันตรายกว่าไม่มีเพดานเลย
    เพราะคนอ่านไฟล์แล้วเชื่อว่าระบบกันให้อยู่

    `deny` ยกเว้นได้ตั้งใจ — มีชื่อที่ต้องไม่มีวันมีอยู่จริงในโค้ด (diagnosis.any,
    shell.execute) เป็นกับดักไว้ล่วงหน้า
    """
    from care_addons.ap_policy.engine import load_policy
    from care_addons.ap_policy.profile import load_profile

    known = set(load_policy().capabilities)
    unknown = [c for c in load_profile().allow if c not in known]
    assert not unknown, (
        "capability ใน profiles/care-agent/profile.yaml (tools.allow) "
        f"ที่ไม่มีใน policies/care-authority-map.yaml: {unknown}"
    )


def test_profile_denies_everything_that_must_never_be_autonomous():
    """action ที่ประกาศว่า autonomous=False ต้องอยู่ใน deny หรืออย่างน้อยไม่อยู่ใน allow

    ไม่งั้นจะมีช่องที่ agent เรียก action ซึ่ง "ต้องมีคนเกี่ยวข้อง" ได้เอง
    """
    import care_addons.care_careplan.services
    import care_addons.care_medication.services  # noqa: F401
    from care_addons.ap_policy.profile import load_profile
    from care_addons.ap_policy.services import DECLARED

    profile = load_profile()
    leaked = [
        capability
        for capability, meta in DECLARED.items()
        if not meta["autonomous"] and profile.allows(capability) and not profile.denies(capability)
    ]
    assert not leaked, f"action ที่ต้องมีคนสั่ง แต่ profile ปล่อยให้ agent เรียกได้: {leaked}"


def test_destructive_conformance_scripts_refuse_a_real_database():
    """สคริปต์ที่ลบทั้ง schema ต้องปฏิเสธตัวเองถ้าไม่ได้ตั้งใจ

    ทั้งสามตัวถูก copy เข้า Docker image (เพื่อให้รัน db_role_check จากในเครือข่ายของ DB ได้)
    ผู้ดูแลที่ exec เข้า container แล้วรัน rls_check เพื่อ "ตรวจว่า RLS ยังทำงานไหม"
    เคยลบข้อมูลผู้ป่วยไปทั้งชุด — เจอจริงตอนทดสอบ docker compose ของ M5
    """
    import subprocess

    env = {
        **os.environ,
        "PSTACK_DATABASE_URL": "postgresql+asyncpg://care:care@127.0.0.1:1/pretend",
    }
    env.pop("CONFORMANCE_ALLOW_DESTRUCTIVE", None)
    for script in ("rls_check.py", "migration_check.py", "payload_check.py"):
        result = subprocess.run(
            [sys.executable, str(ROOT / "conformance" / script)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,      # เราตรวจ exit code เอง — ต้องเป็น 2 ไม่ใช่ 0
        )
        assert result.returncode == 2, f"{script} ไม่ได้ปฏิเสธ DB จริง (exit {result.returncode})"
        assert "DROP SCHEMA" in result.stderr, script
        # ห้ามให้รหัสผ่านหลุดออกมาในข้อความเตือน
        assert "care:care" not in result.stderr, f"{script} พิมพ์ credential ออกมาด้วย"
