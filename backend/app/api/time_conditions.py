from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import TimeCondition, TimeGroup
from app.schemas import (
    TimeConditionCreate,
    TimeConditionOut,
    TimeConditionUpdate,
    TimeGroupCreate,
    TimeGroupOut,
    TimeGroupUpdate,
)
from app.services.esl import reloadxml

router = APIRouter(prefix="/api/time-conditions", tags=["time-conditions"])


# ---------- Grupos de Horarios (Time Groups) ----------

@router.get("/groups", response_model=list[TimeGroupOut])
async def list_time_groups(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(TimeGroup).order_by(TimeGroup.name))
    return result.scalars().all()


@router.post("/groups", response_model=TimeGroupOut, status_code=status.HTTP_201_CREATED)
async def create_time_group(payload: TimeGroupCreate, session: AsyncSession = Depends(get_session)):
    group = TimeGroup(**payload.model_dump())
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


@router.put("/groups/{group_id}", response_model=TimeGroupOut)
async def update_time_group(
    group_id: int, payload: TimeGroupUpdate, session: AsyncSession = Depends(get_session)
):
    group = await session.get(TimeGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo de horario no encontrado")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await session.commit()
    await session.refresh(group)
    try:
        await reloadxml()
    except Exception:
        pass
    return group


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_time_group(group_id: int, session: AsyncSession = Depends(get_session)):
    group = await session.get(TimeGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo de horario no encontrado")
    await session.delete(group)
    await session.commit()


# ---------- Condiciones de Tiempo (Time Conditions) ----------

@router.get("", response_model=list[TimeConditionOut])
async def list_time_conditions(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(TimeCondition).order_by(TimeCondition.id))
    return result.scalars().all()


@router.post("", response_model=TimeConditionOut, status_code=status.HTTP_201_CREATED)
async def create_time_condition(
    payload: TimeConditionCreate, session: AsyncSession = Depends(get_session)
):
    condition = TimeCondition(**payload.model_dump())
    session.add(condition)
    await session.commit()
    await session.refresh(condition)
    try:
        await reloadxml()
    except Exception:
        pass
    return condition


@router.put("/{condition_id}", response_model=TimeConditionOut)
async def update_time_condition(
    condition_id: int, payload: TimeConditionUpdate, session: AsyncSession = Depends(get_session)
):
    condition = await session.get(TimeCondition, condition_id)
    if not condition:
        raise HTTPException(status_code=404, detail="Condición de tiempo no encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(condition, field, value)
    await session.commit()
    await session.refresh(condition)
    try:
        await reloadxml()
    except Exception:
        pass
    return condition


@router.delete("/{condition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_time_condition(condition_id: int, session: AsyncSession = Depends(get_session)):
    condition = await session.get(TimeCondition, condition_id)
    if not condition:
        raise HTTPException(status_code=404, detail="Condición de tiempo no encontrada")
    await session.delete(condition)
    await session.commit()
    try:
        await reloadxml()
    except Exception:
        pass
