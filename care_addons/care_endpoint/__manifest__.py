{
    "name": "care_endpoint",
    "version": "0.1.0",
    "depends": ["tenancy", "ap_audit", "ap_policy", "care_patient"],
    "summary": "การกระทำต่ออุปกรณ์ — โดเมนตัดสินและบันทึก endpoint เป็นคนลงมือ "
    "capability ชนิดแรกของระบบที่เปลี่ยนสภาพแวดล้อมของผู้ป่วย (ADR-0015) "
    "ไม่มีโค้ดที่คุยกับอุปกรณ์ในโมดูลนี้โดยเจตนา และไม่เก็บพฤติกรรมการดูสื่อ",
    "permissions": ["care.endpoint.act"],
}
