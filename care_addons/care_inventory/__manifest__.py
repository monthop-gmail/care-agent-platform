{
    "name": "care_inventory",
    "version": "0.1.0",
    "depends": ["tenancy", "ap_audit", "ap_policy", "care_patient", "care_escalation"],
    "summary": "ของกิน/ของใช้ที่บ้าน + วันหมดอายุ — ตอบว่า 'มีอยู่แล้วนะ' ก่อนซื้อซ้ำ "
    "แต่ไม่ห้ามซื้อ (contracts/inventory/v1)",
    "permissions": ["care.inventory.read", "care.inventory.manage"],
}
