from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import PriorityNumber, SystemSettings
from app.schemas import PriorityCreate, PriorityOut
from app.services.esl import reloadxml

router = APIRouter(prefix="/api/priority-numbers", tags=["priority-numbers"])

DEFAULT_ANNOUNCE = "Llamada prioritaria. Un asesor lo atenderá en breve."


async def _get_settings(session: AsyncSession) -> SystemSettings:
    row = await session.get(SystemSettings, 1)
    if not row:
        # La semilla normal la hace settings_api.get_or_create_settings; acá
        # solo se lee, y si no existe todavía se devuelve el texto por defecto.
        return None  # type: ignore
    return row


async def _reload() -> None:
    try:
        await reloadxml()
    except Exception:
        pass


@router.get("")
async def list_priority(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PriorityNumber).order_by(PriorityNumber.created_at.desc()))
    numbers = result.scalars().all()
    row = await session.get(SystemSettings, 1)
    announce_text = (row.priority_announce_text if row else None) or DEFAULT_ANNOUNCE
    return {
        "numbers": [PriorityOut.model_validate(n).model_dump() for n in numbers],
        "announce_text": announce_text,
    }


@router.post("", response_model=PriorityOut, status_code=status.HTTP_201_CREATED)
async def add_priority(payload: PriorityCreate, session: AsyncSession = Depends(get_session)):
    number = payload.number.strip()
    existing = (
        await session.execute(select(PriorityNumber).where(PriorityNumber.number == number))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"El número {number} ya está en la lista de prioridad")
    item = PriorityNumber(number=number, note=payload.note)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    await _reload()
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_priority(item_id: int, session: AsyncSession = Depends(get_session)):
    item = await session.get(PriorityNumber, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Número no encontrado en la lista de prioridad")
    await session.delete(item)
    await session.commit()
    await _reload()


class PriorityAnnounceUpdate(BaseModel):
    text: str


@router.put("/announce")
async def update_announce(payload: PriorityAnnounceUpdate, session: AsyncSession = Depends(get_session)):
    """Texto del anuncio que se le dice al llamante VIP al entrar a una cola."""
    row = await session.get(SystemSettings, 1)
    if not row:
        raise HTTPException(status_code=404, detail="Ajustes no encontrados")
    row.priority_announce_text = payload.text.strip()
    await session.commit()
    await _reload()
    return {"announce_text": row.priority_announce_text}
