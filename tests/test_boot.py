"""ระบบต้องบูตขึ้นพร้อมทุกโมดูล — ถ้าเทสนี้แดง แปลว่า addon ไหนสักตัวพัง"""

from tests.conftest import MODULES


def test_healthz_lists_all_modules(client):
    body = client.get("/healthz").json()
    for module in MODULES:
        assert module in body["modules"], f"โมดูล {module} ไม่ถูกโหลด"


def test_platform_and_care_routes_mounted(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in [
        "/api/platform/tenants",
        "/api/platform/consents",
        "/api/platform/audit/events",
        "/api/platform/policy/capabilities",
        "/api/care/patients",
        "/api/care/routines",
        "/api/care/jobs/tick",
        "/api/care/appointments",
        "/api/care/appointments/{appointment_id}/visit-brief",
        "/api/care/orientation/daily-brief",
        "/api/care/orientation/date",
    ]:
        assert path in paths, f"ไม่พบ route {path}"
