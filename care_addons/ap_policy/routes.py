from __future__ import annotations

from fastapi import APIRouter

from care_addons.ap_policy.engine import RISK_ORDER, load_policy
from care_addons.ap_policy.services import DECLARED
from care_addons.ap_tenancy.deps import ScopeDep

router = APIRouter(prefix="/api/platform/policy", tags=["platform: policy"])


@router.get("/capabilities")
async def list_capabilities(scope: ScopeDep) -> dict:
    """ดูว่า capability ไหน risk เท่าไร และต้องการ authority ระดับใด — ใช้ตรวจสอบย้อนหลังได้"""
    policy = load_policy()
    rows = []
    for capability in sorted(set(policy.capabilities) | set(DECLARED)):
        decision = policy.evaluate(capability)
        rows.append(
            {
                "capability": capability,
                "action_risk": decision.action_risk,
                "authority": decision.authority,
                "agent_may_act_alone": decision.may_act_now,
                "declared_in_code": capability in DECLARED,
                "reason": decision.reason,
            }
        )
    return {
        "policy_id": policy.policy_id,
        "risk_levels": RISK_ORDER,
        "authority_map": policy.authority_map,
        "capabilities": rows,
    }
