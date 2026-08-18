from __future__ import annotations

from fastapi import APIRouter, HTTPException

from care_addons.ap_tenancy.deps import ScopeDep, SessionDep
from care_addons.care_orientation import services as svc

router = APIRouter(prefix="/api/care/orientation", tags=["care: orientation"])


@router.get("/date")
async def what_day_is_it(patient_id: str, scope: ScopeDep, session: SessionDep) -> dict:
    """วันนี้วันอะไร — ถามซ้ำกี่ครั้งก็ได้คำตอบเดิม"""
    answer = await svc.answer_date(session, scope, patient_id)
    await session.commit()
    return answer


@router.get("/layers")
async def layers(patient_id: str, scope: ScopeDep, session: SessionDep) -> dict:
    """ทั้ง 5 ชั้น: เวลา · วันที่ · สถานที่ · คน · แผน"""
    return await svc.five_layers(session, scope, patient_id)


@router.get("/daily-brief")
async def daily_brief(patient_id: str, scope: ScopeDep, session: SessionDep) -> dict:
    """"วันนี้ของคุณ" — หน้าหลักของผู้ป่วย"""
    brief = await svc.daily_brief(session, scope, patient_id)
    await session.commit()
    return brief


@router.get("/plan")
async def plan_for(
    patient_id: str, expression: str, scope: ScopeDep, session: SessionDep
) -> dict:
    """เช่น ?expression=พรุ่งนี้ — resolve เป็นวันที่จริงแล้วค้นจาก timeline"""
    try:
        answer = await svc.what_happens_on(session, scope, patient_id, expression)
    except svc.UnknownTimeExpression as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return answer


@router.get("/people")
async def people(patient_id: str, scope: ScopeDep, session: SessionDep) -> list[dict]:
    return await svc.who_is_around(session, scope, patient_id)
