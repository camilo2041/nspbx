import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import InboundRoute
from app.schemas import InboundRouteCreate, InboundRouteOut, InboundRouteUpdate
from app.services.esl import reloadxml

router = APIRouter(prefix="/api/inbound-routes", tags=["inbound-routes"])


def _normalizar_did_pattern(pattern: str) -> str:
    """El patrón se pega TAL CUAL dentro de `^{pattern}$` para armar la
    expresión regular del dialplan (ver config_generator.py) — nunca se
    valida ni se escapa. Un DID copiado de un proveedor en formato
    internacional ("+573001234567") rompe esa expresión (un "+" inicial no
    tiene nada que cuantificar) y la ruta queda muerta en silencio: se ve
    "Activa" en el panel pero ninguna llamada real la hace matchear nunca.

    Se le quita el "+" inicial (el caso real más probable) y se valida que
    lo que quede compile como regex — cualquier otro patrón inválido se
    rechaza acá, antes de guardar, en vez de fallar en silencio en
    FreeSWITCH."""
    limpio = pattern.strip()
    if limpio.lower() in ("any", "*", ""):
        return limpio
    if limpio.startswith("+"):
        limpio = limpio[1:]
    try:
        re.compile(f"^{limpio}$")
    except re.error as exc:
        raise HTTPException(
            status_code=400,
            detail=f"El patrón '{pattern}' no es una expresión válida para el dialplan: {exc}",
        )
    return limpio


@router.get("", response_model=list[InboundRouteOut])
async def list_routes(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(InboundRoute).order_by(InboundRoute.priority, InboundRoute.id))
    return result.scalars().all()


@router.post("", response_model=InboundRouteOut, status_code=status.HTTP_201_CREATED)
async def create_route(payload: InboundRouteCreate, session: AsyncSession = Depends(get_session)):
    data = payload.model_dump()
    data["did_pattern"] = _normalizar_did_pattern(data["did_pattern"])
    route = InboundRoute(**data)
    session.add(route)
    await session.commit()
    await session.refresh(route)
    try:
        await reloadxml()
    except Exception:
        pass
    return route


@router.get("/{route_id}", response_model=InboundRouteOut)
async def get_route(route_id: int, session: AsyncSession = Depends(get_session)):
    route = await session.get(InboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    return route


@router.put("/{route_id}", response_model=InboundRouteOut)
async def update_route(route_id: int, payload: InboundRouteUpdate, session: AsyncSession = Depends(get_session)):
    route = await session.get(InboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    updates = payload.model_dump(exclude_unset=True)
    if "did_pattern" in updates:
        updates["did_pattern"] = _normalizar_did_pattern(updates["did_pattern"])
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
    route = await session.get(InboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    await session.delete(route)
    await session.commit()
    try:
        await reloadxml()
    except Exception:
        pass
