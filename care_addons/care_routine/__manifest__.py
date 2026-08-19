{
    "name": "care_routine",
    "version": "0.1.0",
    "depends": ["tenancy", "ap_audit", "ap_policy", "care_patient", "care_escalation"],
    "summary": "กิจวัตรประจำวันและมื้ออาหาร — สร้าง care job ตามตารางของผู้ป่วย (ตาม timezone ของผู้ป่วย)",
    "permissions": ["care.routine.read", "care.routine.manage"],
}
