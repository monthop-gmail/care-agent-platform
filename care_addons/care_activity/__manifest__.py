{
    "name": "care_activity",
    "version": "0.1.0",
    "depends": ["ap_tenancy", "ap_audit", "ap_policy", "care_patient", "care_escalation"],
    "summary": "งานหลายขั้นตอนที่ 'เริ่มได้แต่ทำไม่จบ' — ซักผ้า ทำอาหาร "
    "agent ช่วยทำให้จบ ไม่ใช่แค่เตือนให้เริ่ม · ขั้นที่ค้างนานเกินกลายเป็น care.task.stalled",
    "permissions": ["care.activity.read", "care.activity.manage"],
}
