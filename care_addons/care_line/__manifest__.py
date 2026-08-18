{
    "name": "care_line",
    "version": "0.1.0",
    "depends": [
        "ap_tenancy",
        "ap_audit",
        "ap_policy",
        "care_patient",
        "care_escalation",
        "care_routine",
        "care_medication",
        "care_journal",
        "care_orientation",
        "line_oa",
    ],
    "summary": "ช่องทาง LINE ของผู้ป่วยและผู้ดูแล — ส่ง reminder ออกจริง, รับคำยืนยันกลับ, "
    "ตอบคำถาม orientation แบบ deterministic (ไม่ผ่าน LLM — ADR-0008)",
    "permissions": ["care.line.manage"],
}
