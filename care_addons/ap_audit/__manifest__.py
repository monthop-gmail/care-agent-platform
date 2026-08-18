{
    "name": "ap_audit",
    "version": "0.1.0",
    "depends": ["ap_tenancy"],
    "summary": "Platform conformance: append-only audit event store ตาม agent-platform event/v1 "
    "— ทุก state change ในระบบต้องผ่านที่นี่ (no silent state change)",
    "permissions": ["platform.audit.read"],
}
