{
    "name": "ap_approval",
    "version": "0.1.0",
    "depends": ["tenancy", "ap_audit", "ap_policy"],
    "summary": "Platform conformance: คำขออนุมัติและคำตัดสินของผู้มีอำนาจ ตาม agent-platform approval/v1 "
    "— policy บอกว่าต้องขออนุมัติไหม ที่นี่คือคำตัดสินหลังจากนั้น",
    "permissions": ["platform.approval.read", "platform.approval.decide"],
}
