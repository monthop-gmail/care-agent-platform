{
    "name": "care_medication",
    "version": "0.1.0",
    "depends": ["ap_tenancy", "ap_audit", "ap_policy", "ap_approval", "care_patient", "care_escalation"],
    "summary": "Medication memory — append-only version chain, ก่อน/หลังอาหารเป็น structured data, "
    "รู้ว่าหมอคนไหนสั่ง และ detect conflict โดยไม่เลือกข้าง (ADR-0005, ADR-0006)",
    "permissions": ["care.medication.read", "care.medication.manage"],
}
