from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import BlacklistNumber
from app.schemas import BlacklistCreate, BlacklistOut
from app.services.esl import reloadxml

router = APIRouter(prefix="/api/blacklist", tags=["blacklist"])


@router.get("", response_model=list[BlacklistOut])
async def list_blacklist(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(BlacklistNumber).order_by(BlacklistNumber.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=BlacklistOut, status_code=status.HTTP_201_CREATED)
async def add_to_blacklist(payload: BlacklistCreate, session: AsyncSession = Depends(get_session)):
    phone = payload.phone.strip()
    existing = (
        await session.execute(select(BlacklistNumber).where(BlacklistNumber.phone == phone))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400, detail=f"El número {phone} ya está en la lista negra"
        )
    item = BlacklistNumber(phone=phone, note=payload.note)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    try:
        await reloadxml()
    except Exception:
        pass
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_blacklist(item_id: int, session: AsyncSession = Depends(get_session)):
    item = await session.get(BlacklistNumber, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Número no encontrado en lista negra")
    await session.delete(item)
    await session.commit()
    try:
        await reloadxml()
    except Exception:
        pass
