import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.runtime_settings import runtime_settings
from app.models import Extension, Queue, SystemSettings
from app.schemas import QueueCreate, QueueTtsRequest, QueueUpdate
from app.services import deepgram, esl, greetings, tts, tts_elevenlabs
from app.services.queues_sync import parse_agents, remove_queue, sync_queue, write_callcenter_conf

router = APIRouter(prefix="/api/queues", tags=["queues"])


async def _synthesize(text: str, voice: str, provider: str, session: AsyncSession) -> tuple[bytes, str]:
    """(audio, extensión) para el anuncio de la cola — mismos proveedores y
    formatos que el saludo de los voizbots (ver app/api/voicebots.py)."""
    if provider == "elevenlabs":
        row = await session.get(SystemSettings, 1)
        api_key = (row.elevenlabs_api_key if row else None) or ""
        return await tts_elevenlabs.synthesize(text, voice, api_key), "wav"
    if provider == "deepgram":
        row = await session.get(SystemSettings, 1)
        return await deepgram.synthesize(text, voice, (row.deepgram_api_key if row else None) or ""), "wav"
    return await tts.synthesize(text, voice), "mp3"


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
        "announce_audio_path": queue.announce_audio_path,
        "announce_tts_text": queue.announce_tts_text,
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
    greetings.remove_queue_announce(queue.id)
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


@router.post("/{queue_id}/announce")
async def upload_queue_announce(queue_id: int, file: UploadFile, session: AsyncSession = Depends(get_session)):
    """Sube un archivo (WAV/MP3) como anuncio de entrada de la cola. El
    dialplan (ver _append_queue_routes en config_generator.py) lo reproduce
    apenas contesta, antes de la música de espera — se sirve en vivo por
    mod_xml_curl, así que no hace falta recargar nada."""
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="El archivo supera los 25 MB")
    try:
        path = greetings.save_queue_announce(queue.id, file.filename or "anuncio.wav", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    queue.announce_audio_path = path
    queue.announce_tts_text = None
    await session.commit()
    await session.refresh(queue)
    return _out(queue)


@router.post("/{queue_id}/announce/tts")
async def generate_queue_announce_tts(
    queue_id: int, payload: QueueTtsRequest, session: AsyncSession = Depends(get_session)
):
    """Genera el anuncio con voz sintética (edge gratis, o ElevenLabs si está
    configurada la key) y lo deja como el anuncio de entrada de la cola."""
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    try:
        audio, ext = await _synthesize(payload.text, payload.voice, payload.provider, session)
        path = greetings.save_queue_announce(queue.id, f"anuncio.{ext}", audio)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error generando el anuncio: {exc}")
    queue.announce_audio_path = path
    queue.announce_tts_text = payload.text
    await session.commit()
    await session.refresh(queue)
    return _out(queue)


@router.delete("/{queue_id}/announce")
async def delete_queue_announce(queue_id: int, session: AsyncSession = Depends(get_session)):
    """Quita el anuncio: la cola vuelve a entrar directo a la música de espera."""
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    greetings.remove_queue_announce(queue.id)
    queue.announce_audio_path = None
    queue.announce_tts_text = None
    await session.commit()
    await session.refresh(queue)
    return _out(queue)


@router.get("/{queue_id}/announce/audio")
async def queue_announce_audio(queue_id: int, session: AsyncSession = Depends(get_session)):
    """Sirve el anuncio para escucharlo en el panel (va por api.getBlob en el
    front, que manda el token)."""
    queue = await session.get(Queue, queue_id)
    if not queue or not queue.announce_audio_path:
        raise HTTPException(status_code=404, detail="Sin anuncio configurado")
    p = Path(queue.announce_audio_path)
    media = "audio/mpeg" if p.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(p, media_type=media)
