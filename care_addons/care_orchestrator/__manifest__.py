{
    "name": "care_orchestrator",
    "version": "0.1.0",
    "depends": [
        "tenancy",
        "ap_consent",
        "ap_audit",
        "ap_policy",
        "ap_approval",
        "care_patient",
        "care_escalation",
        "care_routine",
        "care_medication",
        "care_appointment",
        "care_careplan",
        "care_activity",
        "care_safety",
        "care_organization",
    ],
    "summary": "รอบวันของการดูแล — สร้างงานประจำวันให้ทุกคน สรุปประจำวันจากข้อเท็จจริงที่วัดได้ "
    "และดูแลคิวรออนุมัติให้หมดอายุอย่างปลอดภัย (ADR-0004 ข้อ 4, ADR-0006, ADR-0009)",
    "permissions": ["care.summary.read"],
}
