{
    "name": "care_safety",
    "version": "0.1.0",
    "depends": ["tenancy", "ap_audit", "ap_policy", "care_patient", "care_escalation"],
    "summary": "สัญญาณความปลอดภัยจากภายนอก (GPS · wearable · sensor) — sensor รายงานสิ่งที่วัดได้ "
    "ไม่ใช่การวินิจฉัย · confidence ต่ำไม่ปลุกคน · สัญญาณซ้ำไม่ปลุกซ้ำ (contracts/safety/v1)",
    "permissions": ["care.safety.read", "care.safety.manage"],
}
