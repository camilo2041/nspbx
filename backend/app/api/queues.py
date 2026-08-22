import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.runtime_settings import runtime_settings
from app.models import Extension, Queue
from app.schemas import QueueCreate, QueueUpdate
from app.services import esl
from app.services.queues_sync import parse_agents, remove_queue, sync_queue, write_callcenter_conf

router = APIRouter(prefix="/api/queues", tags=["queues"])


async def _chocar_con_extension(session: AsyncSession, numero: str) -> None:
    """Nada impedía crear una cola con el mismo número que una extensión
    real — en el dialplan, `Local_Extension` se genera ANTES que las
    colas y gana siempre (ver config_generator.py), así que la cola
    quedaba inalcanzable por ese número, sin ningún aviso en el panel."""
    existe = (await session.execute(select(Extension).where(Extension.number == numero))).scalar_one_or_none()
    if existe:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe una extensión con el número {numero} — una cola con ese mismo número quedaría inalcanzable.",
        )


def _out(queue: Queue) -> dict:
    return {
        "id": queue.id,
        "name": queue.name,
        "extension": queue.extension,
        "strategy": queue.strategy,
        "moh_sound": queue.moh_sound,
        "agents": parse_agents(queue.agents),
        "max_wait_time": queue.max_wait_time,
        "max_wait_time_with_no_agent": queue.max_wait_time_with_no_agent,
        "agent_ring_timeout": queue.agent_ring_timeout,
        "max_no_answer": queue.max_no_answer,
        "wrap_up_time": queue.wrap_up_time,
        "record": queue.record,
        "failover_extension": queue.failover_extension,
        "announce_position": queue.announce_position,
        "enabled": queue.enabled,
        "created_at": queue.created_at,
    }


async def _rewrite_conf_file(session: AsyncSession) -> None:
    """Regenera callcenter.conf.xml completo (necesario porque los agentes
    se declaran ahí con todos sus parámetros) y refresca el árbol XML en
    memoria de FreeSWITCH. `reloadxml` NO reinicia mod_callcenter ni
    afecta colas ya cargadas — solo actualiza qué vería un `queue
    load/reload` posterior."""
    rows = (await session.execute(select(Queue))).scalars().all()
    write_callcenter_conf(rows)
    try:
        await esl.api("reloadxml")
    except Exception:
        pass


@router.get("")
async def list_queues(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Queue).order_by(Queue.id))
    return [_out(q) for q in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_queue(payload: QueueCreate, session: AsyncSession = Depends(get_session)):
    await _chocar_con_extension(session, payload.extension)
    data = payload.model_dump()
    agents = data.pop("agents")
    queue = Queue(**data, agents=json.dumps(agents))
    session.add(queue)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Nombre o extensión de cola duplicados")
    await session.refresh(queue)
    await _rewrite_conf_file(session)
    await sync_queue(queue)
    return _out(queue)


@router.get("/{queue_id}")
async def get_queue(queue_id: int, session: AsyncSession = Depends(get_session)):
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    return _out(queue)


@router.put("/{queue_id}")
async def update_queue(queue_id: int, payload: QueueUpdate, session: AsyncSession = Depends(get_session)):
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    old_name = queue.name
    data = payload.model_dump(exclude_unset=True)
    if "extension" in data and data["extension"] != queue.extension:
        await _chocar_con_extension(session, data["extension"])
    if "agents" in data:
        data["agents"] = json.dumps(data["agents"])
    for field, value in data.items():
        setattr(queue, field, value)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Nombre o extensión de cola duplicados")
    await session.refresh(queue)
    await _rewrite_conf_file(session)
    if old_name != queue.name:
        # Si cambió el nombre, la cola vieja queda huérfana en mod_callcenter.
        await remove_queue(old_name)
    await sync_queue(queue)
    return _out(queue)


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue_endpoint(queue_id: int, session: AsyncSession = Depends(get_session)):
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    name = queue.name
    await session.delete(queue)
    await session.commit()
    await _rewrite_conf_file(session)
    await remove_queue(name)


@router.get("/{queue_id}/status")
async def queue_status(queue_id: int, session: AsyncSession = Depends(get_session)):
    """Consulta en vivo a mod_callcenter: agentes y llamadas en espera,
    para un panel tipo Issabel."""
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    qkey = f"{queue.name}@{runtime_settings.fs_domain}"
    try:
        agents_raw = await esl.api(f"callcenter_config queue list agents {qkey}")
        tiers_raw = await esl.api(f"callcenter_config queue list tiers {qkey}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"agents": agents_raw, "tiers": tiers_raw}
