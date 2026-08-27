import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import Extension, Queue, RingGroup
from app.schemas import RingGroupCreate, RingGroupUpdate
from app.services.esl import reloadxml

router = APIRouter(prefix="/api/ring-groups", tags=["ring-groups"])


def _out(g: RingGroup) -> dict:
    try:
        members = json.loads(g.members or "[]")
    except (ValueError, TypeError):
        members = []
    return {
        "id": g.id,
        "name": g.name,
        "number": g.number,
        "members": members,
        "enabled": g.enabled,
        "created_at": g.created_at,
    }


async def _chocar_con_existente(session: AsyncSession, numero: str) -> None:
    """Un número de grupo no debe chocar con una extensión o una cola: en el
    dialplan esas rutas se evalúan antes y lo taparían sin aviso."""
    if (await session.execute(select(Extension).where(Extension.number == numero))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Ya existe una extensión con el número {numero}")
    if (await session.execute(select(Queue).where(Queue.extension == numero))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Ya existe una cola con el número {numero}")


async def _reload() -> None:
    try:
        await reloadxml()
    except Exception:
        pass


@router.get("")
async def list_ring_groups(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(RingGroup).order_by(RingGroup.id))).scalars().all()
    return [_out(g) for g in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_ring_group(payload: RingGroupCreate, session: AsyncSession = Depends(get_session)):
    await _chocar_con_existente(session, payload.number)
    g = RingGroup(
        name=payload.name, number=payload.number, members=json.dumps(payload.members), enabled=payload.enabled
    )
    session.add(g)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Nombre o número de grupo duplicados")
    await session.refresh(g)
    await _reload()
    return _out(g)


@router.put("/{group_id}")
async def update_ring_group(group_id: int, payload: RingGroupUpdate, session: AsyncSession = Depends(get_session)):
    g = await session.get(RingGroup, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    data = payload.model_dump(exclude_unset=True)
    if "number" in data and data["number"] != g.number:
        await _chocar_con_existente(session, data["number"])
    if "members" in data:
        data["members"] = json.dumps(data["members"])
    for field, value in data.items():
        setattr(g, field, value)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Nombre o número de grupo duplicados")
    await session.refresh(g)
    await _reload()
    return _out(g)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ring_group(group_id: int, session: AsyncSession = Depends(get_session)):
    g = await session.get(RingGroup, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    await session.delete(g)
    await session.commit()
    await _reload()
