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
    client.post(
        "/api/tenancy/tenants", headers=auth, json={"tenant_id": tenant_id, "display_name": "บ้านทดสอบ"}
    )

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
    assert trail[-1]["event_type"] == "JOB_SETTLED"      # ใบปิดท้ายของ trail
    assert "JOB_COMPLETED" in [e["event_type"] for e in trail]
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


def test_approval_queue_over_http(client, care):
    """คิวรออนุมัติเห็นได้จริงผ่าน API — และผู้ยื่นกดอนุมัติให้ตัวเองไม่ได้ (approval/v1)"""
    headers, patient_id = care

    proposed = client.post(
        "/api/care/medications/propose",
        headers=headers,
        json={
            "patient_id": patient_id,
            "name": "Med Queue",
            "schedule": [{"time": "21:00", "relation_to_meal": "bedtime", "dose": "1 tablet"}],
            "instruction_source": "doctor_instruction",
        },
    )
    assert proposed.status_code == 201, proposed.text
    version_id = proposed.json()["version_id"]

    queue = client.get("/api/platform/approvals", headers=headers).json()
    waiting = [row for row in queue if row["subject"]["id"] == version_id]
    assert len(waiting) == 1
    assert waiting[0]["capability"] == "medication.regimen.write"
    assert waiting[0]["authority_required"] == "human_command_required"
    assert waiting[0]["expires_at"] is None      # รอได้ตลอดกาล (ADR-0009)

    # 🔒 authority มาจาก session ของผู้ใช้ ส่งมาใน body ไม่ได้ — และคนที่ยื่นคือคนที่ล็อกอินอยู่
    denied = client.post(
        f"/api/platform/approvals/{waiting[0]['request_id']}/decide",
        headers=headers,
        json={"decision": "APPROVE", "reason": "อนุมัติเอง"},
    )
    assert denied.status_code == 422
    assert "ตัวเอง" in denied.json()["detail"]

    current = client.get(f"/api/care/medications/current?patient_id={patient_id}", headers=headers)
    assert "Med Queue" not in [row["name"] for row in current.json()]

    # กดยืนยันตรง ๆ = human command — คำขอออกจากคิวโดยไม่กลายเป็นใบอนุมัติ
    confirmed = client.post(f"/api/care/medications/{version_id}/confirm", headers=headers)
    assert confirmed.status_code == 200
    after = client.get("/api/platform/approvals", headers=headers).json()
    assert [row for row in after if row["subject"]["id"] == version_id] == []


def test_daily_summary_over_http(client, care):
    headers, patient_id = care

    preview = client.get(f"/api/care/summary/{patient_id}", headers=headers)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["summary_id"] is None            # ยังไม่ได้ส่ง = ยังไม่มีใบ
    assert body["facts"]["local_date"] == body["local_date"]
    assert "ไม่ได้ยืนยันไม่ได้แปลว่าไม่ได้ทำ" in body["text"]

    sent = client.post(f"/api/care/summary/{patient_id}/send", headers=headers)
    assert sent.status_code == 200, sent.text

    again = client.post(f"/api/care/summary/{patient_id}/send", headers=headers)
    assert again.status_code == 409              # วันละครั้ง


def test_careplan_over_http(client, care):
    """คำสั่งหลังพบหมอ: จด → เข้าคิว → ยืนยัน → กลายเป็นงานจริง"""
    headers, patient_id = care

    proposed = client.post(
        "/api/care/careplan",
        headers=headers,
        json={
            "patient_id": patient_id,
            "task_type": "exercise",
            "description": "เดินรอบบ้านหลังอาหารเย็น",
            "frequency": {"type": "daily"},
            "source": {"kind": "doctor_visit"},
            "scheduled_times": ["17:30"],
            "duration_minutes": 20,
        },
    )
    assert proposed.status_code == 201, proposed.text
    task_id = proposed.json()["task_id"]
    assert proposed.json()["status"] == "proposed"

    queue = client.get("/api/platform/approvals", headers=headers).json()
    waiting = [row for row in queue if row["subject"]["id"] == task_id]
    assert len(waiting) == 1
    assert waiting[0]["capability"] == "careplan.task.activate"

    # ยังไม่มีบันทึก = ตอบว่าข้อมูลไม่พอ ไม่ใช่ 0%
    adherence = client.get(f"/api/care/careplan/{task_id}/adherence", headers=headers).json()
    assert adherence["available"] is False

    activated = client.post(f"/api/care/careplan/{task_id}/activate", headers=headers)
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"
    assert activated.json()["activated_by"]["type"] == "human"

    # ยืนยันตรง ๆ แล้วคำขอออกจากคิว โดยไม่กลายเป็นใบอนุมัติ
    after = client.get("/api/platform/approvals", headers=headers).json()
    assert [row for row in after if row["subject"]["id"] == task_id] == []

    paused = client.post(
        f"/api/care/careplan/{task_id}/status",
        headers=headers,
        json={"status": "paused", "reason": "ปวดเข่า หมอให้พักก่อน"},
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    # กลับมา active ต้องผ่านทางที่บังคับว่าต้องมีคน ไม่ใช่ /status
    rejected = client.post(
        f"/api/care/careplan/{task_id}/status",
        headers=headers,
        json={"status": "active", "reason": "กลับมาเดินต่อ"},
    )
    assert rejected.status_code == 422
    assert "activate_task" in rejected.json()["detail"]


def test_daily_living_over_http(client, care):
    """ของที่บ้าน + ของใช้ประจำตัว — คำตอบเป็นข้อมูล ไม่ใช่คำสั่ง"""
    headers, patient_id = care

    added = client.post(
        "/api/care/inventory",
        headers=headers,
        json={
            "patient_id": patient_id,
            "name": "นมกล่อง",
            "category": "drink",
            "quantity": 6,
            "unit": "กล่อง",
            "location": "ตู้เย็นชั้นบน",
        },
    )
    assert added.status_code == 201, added.text
    assert added.json()["expires_on"] is None      # ไม่รู้ = ไม่เดา

    check = client.get(
        f"/api/care/inventory/check?patient_id={patient_id}&name=นมกล่อง", headers=headers
    ).json()
    assert len(check["already_at_home"]) == 1
    assert "จะซื้อเพิ่มก็ได้" in check["message"]
    assert "blocked" not in check and "forbidden" not in check

    item = client.post(
        "/api/care/home",
        headers=headers,
        json={
            "patient_id": patient_id,
            "kind": "keys",
            "label": "กุญแจบ้าน",
            "home_location": "ตะกร้าข้างประตู",
        },
    )
    assert item.status_code == 201, item.text

    where = client.get(
        f"/api/care/home/where?patient_id={patient_id}&label=กุญแจ", headers=headers
    ).json()
    assert where["found"] is True
    assert "ตะกร้าข้างประตู" in where["message"]

    unknown = client.get(
        f"/api/care/home/where?patient_id={patient_id}&label=แว่นตา", headers=headers
    ).json()
    assert unknown["found"] is False


def test_activity_and_safety_over_http(client, care):
    headers, patient_id = care

    started = client.post(
        "/api/care/activities",
        headers=headers,
        json={"patient_id": patient_id, "activity_type": "laundry", "label": "ซักผ้า"},
    )
    assert started.status_code == 201, started.text
    body = started.json()
    assert len(body["steps"]) == 4
    assert body["steps"][0]["state"] == "in_progress"

    done = client.post(
        f"/api/care/activities/steps/{body['steps'][0]['step_id']}/complete", headers=headers
    )
    assert done.status_code == 200
    assert done.json()["steps"][1]["state"] == "waiting"

    signalled = client.post(
        f"/api/care/activities/{body['activity_id']}/signal",
        headers=headers,
        json={"event": "washing_machine.finished", "source_system": "smart-home-hub"},
    )
    assert signalled.status_code == 200
    after = signalled.json()
    assert after["state"] != "completed"            # 🔒 เครื่องเสร็จ ≠ งานเสร็จ
    assert after["steps"][2]["state"] == "in_progress"

    # safety ยังไม่ได้เปิดใน care_profile ของผู้ป่วยรายนี้
    blocked = client.post(
        "/api/care/safety/signals",
        headers=headers,
        json={
            "patient_id": patient_id,
            "kind": "door_left_open",
            "source": {"kind": "door_sensor", "system": "smart-home-hub"},
        },
    )
    assert blocked.status_code == 422
    assert "care_profile.safety" in blocked.json()["detail"]

    enabled = client.post(
        f"/api/care/patients/{patient_id}/care-profile", headers=headers, json={"safety": True}
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["care_profile"]["safety"] is True

    accepted = client.post(
        "/api/care/safety/signals",
        headers=headers,
        json={
            "patient_id": patient_id,
            "kind": "door_left_open",
            "source": {"kind": "door_sensor", "system": "smart-home-hub"},
            "confidence": 0.9,
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["severity"] == "medium"

    listed = client.get(f"/api/care/safety/events?patient_id={patient_id}", headers=headers).json()
    assert len(listed["open_events"]) == 1
    # 🔒 รายการว่างไม่ได้แปลว่าปลอดภัย — API ต้องพูดเรื่องนี้เอง
    assert "ไม่ได้แปลว่าที่เหลือปลอดภัย" in listed["note"]


def test_organization_access_over_http(client, care):
    """หมอจากโรงพยาบาล → ได้สิทธิ์ → ลาออก → สิทธิ์หายทันที (ADR-0010)"""
    headers, patient_id = care

    org = client.post(
        "/api/care/organizations",
        headers=headers,
        json={"name": "โรงพยาบาลตัวอย่าง", "kind": "hospital", "external_ref": "HOSP-001"},
    )
    assert org.status_code == 201, org.text
    org_id = org.json()["organization_id"]

    member = client.post(
        f"/api/care/organizations/{org_id}/members",
        headers=headers,
        json={"principal_id": "user-doctor", "display_name": "หมอสมชาย", "role": "doctor"},
    )
    assert member.status_code == 201, member.text
    membership_id = member.json()["membership_id"]

    granted = client.post(
        f"/api/care/organizations/{org_id}/access",
        headers=headers,
        json={
            "patient_id": patient_id,
            "principal_id": "user-doctor",
            "authority_basis": "ผู้ดูแลหลักอนุญาตให้แพทย์เจ้าของไข้ดูข้อมูล",
        },
    )
    assert granted.status_code == 201, granted.text
    assert granted.json()["purpose"] == "clinical_care"
    assert "care.manage" not in granted.json()["scopes"]
    assert granted.json()["conditions"] == [
        {"kind": "org_membership", "params": {"organization_id": org_id}}
    ]

    access = client.get(
        f"/api/care/organizations/access?patient_id={patient_id}", headers=headers
    ).json()
    clinical = [a for a in access if a["organization_id"] == org_id]
    assert len(clinical) == 1 and clinical[0]["conditions_hold"] is True

    ended = client.post(
        f"/api/care/organizations/members/{membership_id}/end",
        headers=headers,
        json={"reason": "ย้ายไปโรงพยาบาลอื่น"},
    )
    assert ended.status_code == 200
    assert ended.json()["active"] is False

    access = client.get(
        f"/api/care/organizations/access?patient_id={patient_id}", headers=headers
    ).json()
    clinical = [a for a in access if a["organization_id"] == org_id]
    # ใบยังอยู่ (ไม่ถูกเพิกถอน) แต่เงื่อนไขไม่เป็นจริงแล้ว → ใช้ไม่ได้
    assert clinical[0]["conditions_hold"] is False
