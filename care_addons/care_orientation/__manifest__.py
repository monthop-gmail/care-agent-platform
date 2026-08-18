{
    "name": "care_orientation",
    "version": "0.1.0",
    "depends": [
        "ap_tenancy",
        "ap_audit",
        "ap_policy",
        "care_patient",
        "care_routine",
        "care_appointment",
        "care_medication",
    ],
    "summary": "Orientation — วันนี้วันอะไร ตอนนี้กี่โมง อยู่ที่ไหน จะพบใคร ต้องทำอะไร "
    "+ daily brief · ถามซ้ำกี่ครั้งก็ตอบเหมือนเดิมโดยไม่ทำให้ผู้ป่วยรู้สึกผิด",
    "permissions": ["care.orientation.read"],
}
