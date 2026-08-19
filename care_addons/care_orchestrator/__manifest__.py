{
    "name": "care_orchestrator",
    "version": "0.1.0",
    "depends": [
        "ap_tenancy",
        "ap_audit",
        "ap_policy",
        "ap_approval",
        "care_patient",
        "care_escalation",
        "care_medication",
        "care_appointment",
    ],
    "summary": "รอบวันของการดูแล — สรุปประจำวันให้ผู้ดูแลจากข้อเท็จจริงที่วัดได้ "
    "และดูแลคิวรออนุมัติให้หมดอายุอย่างปลอดภัย (ADR-0004 ข้อ 4, ADR-0006)",
    "permissions": ["care.summary.read"],
}
