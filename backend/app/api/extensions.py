from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.runtime_settings import runtime_settings
from app.models import Extension, Queue, Trunk
from app.schemas import CallRequest, ExtensionCreate, ExtensionOut, ExtensionUpdate
from app.services.config_generator import orden_troncales
from app.services.esl import originate_bridge, reloadxml

router = APIRouter(prefix="/api/extensions", tags=["extensions"])


async def _chocar_con_cola(session: AsyncSession, numero: str) -> None:
    """Mismo chequeo que api/queues.py, del otro lado: si ya existe una
    cola con este número, una extensión nueva con el mismo número siempre
    gana en el dialplan (Local_Extension se genera antes que las colas,
    ver config_generator.py) y la cola queda inalcanzable sin ningún
    aviso."""
    existe = (await session.execute(select(Queue).where(Queue.extension == numero))).scalar_one_or_none()
    if existe:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe la cola \"{existe.name}\" con el número {numero} — esa cola quedaría inalcanzable.",
        )


@router.get("", response_model=list[ExtensionOut])
async def list_extensions(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Extension).order_by(Extension.number))
    return result.scalars().all()


@router.post("", response_model=ExtensionOut, status_code=status.HTTP_201_CREATED)
async def create_extension(payload: ExtensionCreate, session: AsyncSession = Depends(get_session)):
    await _chocar_con_cola(session, payload.number)
    ext = Extension(**payload.model_dump())
    session.add(ext)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Número de extensión duplicado")
    await session.refresh(ext)
    return ext


@router.get("/{extension_id}", response_model=ExtensionOut)
async def get_extension(extension_id: int, session: AsyncSession = Depends(get_session)):
    ext = await session.get(Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    return ext


@router.put("/{extension_id}", response_model=ExtensionOut)
async def update_extension(
    extension_id: int, payload: ExtensionUpdate, session: AsyncSession = Depends(get_session)
):
    ext = await session.get(Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    data = payload.model_dump(exclude_unset=True)
    if "number" in data and data["number"] != ext.number:
        await _chocar_con_cola(session, data["number"])
    for field, value in data.items():
        setattr(ext, field, value)
    await session.commit()
    await session.refresh(ext)
    return ext


@router.delete("/{extension_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extension(extension_id: int, session: AsyncSession = Depends(get_session)):
    ext = await session.get(Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    await session.delete(ext)
    await session.commit()


@router.post("/{extension_id}/call")
async def call_extension(
    extension_id: int, payload: CallRequest, session: AsyncSession = Depends(get_session)
):
    """Click-to-call: hace sonar la extensión y, al contestar, la bridgea al destino
    (otra extensión interna, o un número externo vía la troncal indicada)."""
    ext = await session.get(Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    if not ext.enabled:
        raise HTTPException(status_code=400, detail="La extensión está deshabilitada")

    destination = payload.destination.strip()

    if payload.trunk_id is not None:
        trunk = await session.get(Trunk, payload.trunk_id)
        if not trunk:
            raise HTTPException(status_code=404, detail="Troncal no encontrada")
        if not trunk.enabled:
            raise HTTPException(status_code=400, detail="La troncal está deshabilitada")
        # La troncal elegida va primero; si hay otras habilitadas, quedan
        # de respaldo — si esta no contesta o la rechaza, FreeSWITCH prueba
        # la siguiente sola, sin que el clic a llamar se pierda por una
        # troncal caída.
        todas_troncales = (await session.execute(select(Trunk))).scalars().all()
        cadena = orden_troncales(todas_troncales, principal_id=trunk.id)
        bridge_target = "|".join(f"sofia/gateway/{t.name}/{destination}" for t in cadena)
    else:
        target_ext = await session.execute(
            select(Extension).where(Extension.number == destination, Extension.enabled.is_(True))
        )
        if not target_ext.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="Destino no es una extensión interna válida; especifica una troncal para llamar a un número externo",
            )
        bridge_target = f"user/{destination}"

    try:
        out = await originate_bridge(
            from_endpoint=f"user/{ext.number}@{runtime_settings.fs_domain}",
            bridge_target=bridge_target,
            caller_id=ext.caller_id_name or ext.number,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"ok": True, "output": out}


@router.post("/reload")
async def extensions_reload():
    try:
        out = await reloadxml()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"ok": True, "output": out}
