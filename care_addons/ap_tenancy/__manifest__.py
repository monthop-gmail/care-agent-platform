{
    "name": "ap_tenancy",
    "version": "0.2.0",
    "depends": ["tenancy", "ap_consent"],
    "summary": "Shim รอบที่ 1 — tenancy ขึ้น kernel แล้ว (pstack v0.3.0) โมดูลนี้เหลือแค่ "
    "re-export ให้ 111 จุดเดิมยังใช้ได้ · รอบที่ 2 จะย้าย import แล้วลบโมดูลนี้ทิ้ง (ADR-0003)",
    "permissions": ["platform.tenancy.manage"],
}
