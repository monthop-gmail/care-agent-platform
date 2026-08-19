{
    "name": "care_appointment",
    "version": "0.1.0",
    "depends": ["tenancy", "ap_audit", "ap_policy", "care_patient", "care_escalation", "care_journal"],
    "summary": "นัดหมาย + กระบวนการไปพบหมอ — reminder ล่วงหน้า, preparation checklist ที่เป็น state จริง, "
    "และ visit brief ที่สร้างจากบันทึกที่มีอยู่เท่านั้น (ห้ามเดาข้อกำหนดทางการแพทย์)",
    "permissions": ["care.appointment.read", "care.appointment.manage"],
}
