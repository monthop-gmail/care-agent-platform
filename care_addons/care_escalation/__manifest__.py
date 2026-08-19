{
    "name": "care_escalation",
    "version": "0.1.0",
    "depends": ["tenancy", "ap_audit", "ap_policy", "care_patient"],
    "summary": "Care job engine — closed loop: เตือน → ยืนยัน → เตือนซ้ำ → ถาม → พลาด → ส่งต่อคน "
    "พร้อม backoff, quiet hours, การรวมการแจ้ง และ audit ครบทุกการเปลี่ยนสถานะ",
    "permissions": ["care.job.read", "care.job.manage"],
}
