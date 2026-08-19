{
    "name": "care_organization",
    "version": "0.1.0",
    "depends": ["tenancy", "ap_consent", "ap_audit", "ap_policy", "care_patient"],
    "summary": "คลินิก/โรงพยาบาล/ร้านยาที่ครอบครัวนี้ใช้จริง + ใครทำงานที่ไหน "
    "— องค์กรไม่ใช่ tenant · สิทธิ์จริง = consent AND สมาชิกภาพที่ยัง active (ADR-0010)",
    "permissions": ["care.organization.read", "care.organization.manage"],
}
