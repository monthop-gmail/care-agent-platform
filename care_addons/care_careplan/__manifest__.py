{
    "name": "care_careplan",
    "version": "0.1.0",
    "depends": [
        "ap_tenancy",
        "ap_audit",
        "ap_policy",
        "ap_approval",
        "care_patient",
        "care_escalation",
        "care_appointment",
    ],
    "summary": "คำสั่งหลังพบหมอ → งานที่เกิดซ้ำจริง (เดิน/ดื่มน้ำ/ทายา/มาตรวจซ้ำ) "
    "— ระบบไม่คิด care plan เอง เก็บตามที่ได้รับ และต้องมีคนยืนยันจึงมีผล (contracts/careplan/v1)",
    "permissions": ["care.careplan.read", "care.careplan.manage"],
}
