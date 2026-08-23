import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import OutboundRoute
from app.schemas import OutboundRouteCreate, OutboundRouteOut, OutboundRouteUpdate
from app.services.esl import reloadxml

router = APIRouter(prefix="/api/outbound-routes", tags=["outbound-routes"])


def _validar_patron_regex(pattern: str) -> str:
    limpio = pattern.strip()
    try:
        re.compile(limpio)
    except re.error as exc:
        raise HTTPException(
            status_code=400,
            detail=f"El patrón '{pattern}' no es una expresión regular válida: {exc}",
        )
    return limpio


@router.get("", response_model=list[OutboundRouteOut])
async def list_routes(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(OutboundRoute).order_by(OutboundRoute.priority, OutboundRoute.id)
    )
    return result.scalars().all()


@router.post("", response_model=OutboundRouteOut, status_code=status.HTTP_201_CREATED)
async def create_route(payload: OutboundRouteCreate, session: AsyncSession = Depends(get_session)):
    data = payload.model_dump()
    data["match_pattern"] = _validar_patron_regex(data["match_pattern"])
    route = OutboundRoute(**data)
    session.add(route)
    await session.commit()
    await session.refresh(route)
    try:
        await reloadxml()
    except Exception:
        pass
    return route


@router.get("/{route_id}", response_model=OutboundRouteOut)
async def get_route(route_id: int, session: AsyncSession = Depends(get_session)):
    route = await session.get(OutboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta saliente no encontrada")
    return route


@router.put("/{route_id}", response_model=OutboundRouteOut)
async def update_route(
    route_id: int, payload: OutboundRouteUpdate, session: AsyncSession = Depends(get_session)
):
    route = await session.get(OutboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta saliente no encontrada")
    updates = payload.model_dump(exclude_unset=True)
    if "match_pattern" in updates and updates["match_pattern"] is not None:
        updates["match_pattern"] = _validar_patron_regex(updates["match_pattern"])
    for field, value in updates.items():
        setattr(route, field, value)
    await session.commit()
    await session.refresh(route)
    try:
        await reloadxml()
    except Exception:
        pass
    return route


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(route_id: int, session: AsyncSession = Depends(get_session)):
    route = await session.get(OutboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta saliente no encontrada")
    await session.delete(route)
    await session.commit()
    try:
        await reloadxml()
    except Exception:
        pass
