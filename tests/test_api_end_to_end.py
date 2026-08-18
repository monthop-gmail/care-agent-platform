"""ผ่าน HTTP จริงทั้งเส้น — login → tenant → patient → routine → tick → ack → audit

เทสอื่นเรียก service ตรงเพื่อคุมเวลาได้ ส่วนไฟล์นี้พิสูจน์ว่า route/auth/consent
ประกอบกันแล้วใช้งานได้จริง
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def token(client) -> str:
    response = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def care(client, token):
    """tenant + patient + consent ผ่าน API ล้วน ๆ"""
    auth = {"Authorization": f"Bearer {token}"}
    tenant_id = "t-api-demo"
    client.post("/api/platform/tenants", headers=auth, json={"tenant_id": tenant_id, "display_name": "บ้านทดสอบ"})

    headers = {**auth, "X-Tenant-Id": tenant_id}
    patient = client.post(
        "/api/care/patients",
        headers=headers,
        json={
            "display_name": "คุณตา",
            "care_profile": {"routine": True, "medication": True, "caregiver_escalation": True},
            "channels": ["line"],
        },
    )
    assert patient.status_code == 201, patient.text
    patient_id = patient.json()["patient_id"]

    me = client.get("/api/users/me", headers=auth).json()
    # ให้ความยินยอมแทนผู้ป่วยได้ แต่ต้องบอกว่าให้แทนโดยอำนาจอะไร (consent/v1)
    without_basis = client.post(
        "/api/platform/consents",
        headers=headers,
        json={
            "subject_id": patient_id,
            "grantee_id": f"user-{me['id']}",
            "scopes": ["care.manage"],
        },
    )
    assert without_basis.status_code == 422
    assert "authority_basis" in without_basis.json()["detail"]

    grant = client.post(
        "/api/platform/consents",
        headers=headers,
        json={
            "subject_id": patient_id,
            "grantee_id": f"user-{me['id']}",
            "scopes": ["care.manage"],
            "authority_basis": "ผู้ดูแลหลักที่ครอบครัวมอบหมาย",
        },
    )
    assert grant.status_code == 201, grant.text
    return headers, patient_id


def test_tenant_header_is_required(client, token):
    """ระบบไม่เดา tenant ให้ — ไม่มี header = ไม่ให้ผ่าน"""
    response = client.get("/api/care/patients", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400
    assert "X-Tenant-Id" in response.json()["detail"]


def test_unknown_tenant_looks_like_not_found(client, token):
    """ไม่ยืนยันให้คนนอกรู้ว่า tenant นี้มีอยู่จริงหรือไม่"""
    response = client.get(
        "/api/care/patients",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": "t-does-not-exist"},
    )
    assert response.status_code in (200, 404)


def test_full_care_loop_over_http(client, care):
    headers, patient_id = care

    routine = client.post(
        "/api/care/routines",
        headers=headers,
        json={
            "patient_id": patient_id,
            "kind": "meal",
            "label": "อาหารเที่ยง",
            "scheduled_time": "12:00",
        },
    )
    assert routine.status_code == 201, routine.text

    materialized = client.post(
        f"/api/care/routines/materialize?patient_id={patient_id}", headers=headers
    )
    assert materialized.status_code == 200
    assert materialized.json()["created"] >= 1

    # เรียกซ้ำต้องไม่สร้างงานซ้ำ
    again = client.post(f"/api/care/routines/materialize?patient_id={patient_id}", headers=headers)
    assert again.json()["created"] == 0

    jobs = client.get(f"/api/care/jobs?patient_id={patient_id}", headers=headers).json()
    assert jobs and jobs[0]["state"] == "pending"

    acknowledged = client.post(
        f"/api/care/jobs/{jobs[0]['care_job_id']}/acknowledge", headers=headers, json={"done": True}
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["state"] == "confirmed"

    trail = client.get(
        f"/api/platform/audit/trail/{jobs[0]['correlation_id']}", headers=headers
    ).json()
    assert trail[0]["event_type"] == "JOB_CREATED"
    assert trail[-1]["event_type"] == "JOB_COMPLETED"
    assert any(e["care_event_type"] == "care.meal.confirmed" for e in trail)


def test_medication_write_needs_a_human_over_http(client, care):
    headers, patient_id = care

    proposed = client.post(
        "/api/care/medications/propose",
        headers=headers,
        json={
            "patient_id": patient_id,
            "name": "Med API",
            "schedule": [{"time": "08:00", "relation_to_meal": "after_meal", "dose": "1 tablet"}],
            "instruction_source": "doctor_instruction",
        },
    )
    assert proposed.status_code == 201, proposed.text
    assert proposed.json()["status"] == "proposed"

    # ยังไม่ยืนยัน = ยังไม่อยู่ใน regimen ปัจจุบัน
    current = client.get(f"/api/care/medications/current?patient_id={patient_id}", headers=headers)
    assert current.json() == []

    confirmed = client.post(
        f"/api/care/medications/{proposed.json()['version_id']}/confirm", headers=headers
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "active"
    assert confirmed.json()["confirmed_by"]["type"] == "human"


def test_policy_catalog_is_inspectable(client, care):
    """ตรวจสอบย้อนหลังได้ว่า capability ไหนต้องการ authority ระดับใด"""
    headers, _ = care
    body = client.get("/api/platform/policy/capabilities", headers=headers).json()
    by_name = {row["capability"]: row for row in body["capabilities"]}

    assert by_name["medication.regimen.write"]["authority"] == "human_command_required"
    assert by_name["medication.regimen.write"]["agent_may_act_alone"] is False
    assert by_name["medication.reminder.send"]["agent_may_act_alone"] is True
