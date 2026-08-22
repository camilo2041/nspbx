import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import VoiceBot
from app.schemas import (
    VoiceBotCreate,
    VoiceBotFlowUpdate,
    VoiceBotNodeTtsRequest,
    VoiceBotOut,
    VoiceBotTtsRequest,
    VoiceBotUpdate,
)
from app.models import SystemSettings
from app.services import ai_intents, deepgram, greetings, tts, tts_elevenlabs
from app.services.esl import reloadxml
from app.services.flow_engine import legacy_flow_from_bot, parse_flow

router = APIRouter(prefix="/api/voicebots", tags=["voicebots"])


async def _get_elevenlabs_key(session: AsyncSession) -> str:
    row = await session.get(SystemSettings, 1)
    return (row.elevenlabs_api_key if row else None) or ""


async def _synthesize(text: str, voice: str, provider: str, session: AsyncSession) -> tuple[bytes, str]:
    """Devuelve (audio, extensión). ElevenLabs y Deepgram entregan WAV
    (PCM 16 kHz) y edge-tts entrega MP3 24 kHz — todos formatos que
    FreeSWITCH reproduce bien en una llamada de 8 kHz."""
    if provider == "elevenlabs":
        api_key = await _get_elevenlabs_key(session)
        return await tts_elevenlabs.synthesize(text, voice, api_key), "wav"
    if provider == "deepgram":
        row = await session.get(SystemSettings, 1)
        return await deepgram.synthesize(text, voice, (row.deepgram_api_key if row else None) or ""), "wav"
    return await tts.synthesize(text, voice), "mp3"


@router.get("/tts/voices")
async def list_tts_voices(provider: str = "edge", session: AsyncSession = Depends(get_session)):
    if provider == "elevenlabs":
        api_key = await _get_elevenlabs_key(session)
        try:
            return await tts_elevenlabs.list_voices(api_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Error consultando ElevenLabs: {exc}")
    if provider == "deepgram":
        # Lista fija: los modelos de Aura-2 son fijos, no dependen de la
        # cuenta como las voces de ElevenLabs.
        return await deepgram.list_voices()
    return tts.SPANISH_VOICES


@router.get("", response_model=list[VoiceBotOut])
async def list_voicebots(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(VoiceBot).order_by(VoiceBot.id))
    return result.scalars().all()


@router.post("", response_model=VoiceBotOut, status_code=status.HTTP_201_CREATED)
async def create_voicebot(payload: VoiceBotCreate, session: AsyncSession = Depends(get_session)):
    if payload.bot_type not in ("ivr", "ai"):
        raise HTTPException(status_code=400, detail="bot_type debe ser 'ivr' o 'ai'")
    bot = VoiceBot(**payload.model_dump())
    session.add(bot)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Nombre de bot duplicado")
    await session.refresh(bot)
    return bot


@router.get("/ai-templates")
async def get_ai_templates():
    """Plantillas para precargar un nodo Agente IA nuevo en el editor de
    flujo (ver ai_intents.plantillas). Va ANTES de /{bot_id} a propósito:
    ese path matchea cualquier segmento único y se quedaría con esta ruta
    primero si estuviera declarada después."""
    return ai_intents.plantillas()


@router.get("/{bot_id}", response_model=VoiceBotOut)
async def get_voicebot(bot_id: int, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    return bot


@router.put("/{bot_id}", response_model=VoiceBotOut)
async def update_voicebot(
    bot_id: int, payload: VoiceBotUpdate, session: AsyncSession = Depends(get_session)
):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(bot, field, value)
    await session.commit()
    await session.refresh(bot)
    return bot


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voicebot(bot_id: int, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    await session.delete(bot)
    await session.commit()
    greetings.remove_greeting(bot_id)
    greetings.remove_all_node_audio(bot_id)


@router.get("/{bot_id}/flow")
async def get_flow(bot_id: int, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    # parse_flow además migra en el momento los nodos IA de la selección
    # fija vieja (transfer + extension="ai_agent") al nuevo tipo "ai_agent"
    # con prompt propio (ver flow_engine._migrar_nodos_ai_legacy) — así el
    # editor ya los muestra migrados sin que el bot se haya reabierto y
    # regrabado antes.
    parsed = parse_flow(bot.flow_json)
    if parsed is not None:
        return parsed
    # Bot creado antes del editor visual: se reconstruye su menú simple
    # (config JSON + saludo) como nodos, para que se vea y se pueda
    # seguir editando en el nuevo editor en vez de aparecer vacío.
    return legacy_flow_from_bot(bot)


@router.put("/{bot_id}/flow")
async def save_flow(bot_id: int, payload: VoiceBotFlowUpdate, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    bot.flow_json = json.dumps({"nodes": payload.nodes, "edges": payload.edges})
    await session.commit()
    try:
        await reloadxml()
    except Exception:
        pass  # el flujo queda guardado igual; el próximo reload lo recoge
    return {"ok": True}


@router.post("/{bot_id}/flow/nodes/{node_id}/audio")
async def upload_node_audio(bot_id: int, node_id: str, file: UploadFile, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    try:
        path = greetings.save_audio(bot_id, file.filename or "audio.wav", content, node_id=node_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"path": path}


@router.post("/{bot_id}/flow/nodes/{node_id}/tts")
async def generate_node_tts(
    bot_id: int, node_id: str, payload: VoiceBotNodeTtsRequest, session: AsyncSession = Depends(get_session)
):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    try:
        audio, ext = await _synthesize(payload.text, payload.voice, payload.provider, session)
        suffix = "whisper" if payload.kind == "whisper" else "audio"
        path = greetings.save_audio(bot_id, f"{suffix}.{ext}", audio, node_id=f"{node_id}_{suffix}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error generando el audio: {exc}")
    return {"path": path}


@router.delete("/{bot_id}/flow/nodes/{node_id}/audio")
async def delete_node_audio(bot_id: int, node_id: str):
    greetings.remove_audio(bot_id, node_id=node_id)
    return {"ok": True}


@router.post("/{bot_id}/greeting", response_model=VoiceBotOut)
async def upload_greeting(
    bot_id: int, file: UploadFile, session: AsyncSession = Depends(get_session)
):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    try:
        path = greetings.save_greeting(bot_id, file.filename or "greeting.wav", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    bot.greeting_audio_path = path
    await session.commit()
    await session.refresh(bot)
    return bot


@router.post("/{bot_id}/tts", response_model=VoiceBotOut)
async def generate_greeting_tts(
    bot_id: int, payload: VoiceBotTtsRequest, session: AsyncSession = Depends(get_session)
):
    """Genera el audio de saludo con una voz neuronal en español (edge-tts,
    gratis, sin API key) y lo deja como el audio propio del bot."""
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    try:
        audio, ext = await _synthesize(payload.text, payload.voice, payload.provider, session)
        path = greetings.save_greeting(bot_id, f"greeting.{ext}", audio)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error generando el audio: {exc}")
    bot.greeting_audio_path = path
    await session.commit()
    await session.refresh(bot)
    return bot


@router.delete("/{bot_id}/greeting", response_model=VoiceBotOut)
async def delete_greeting(bot_id: int, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    greetings.remove_greeting(bot_id)
    bot.greeting_audio_path = None
    await session.commit()
    await session.refresh(bot)
    return bot


@router.post("/reload")
async def voicebots_reload():
    try:
        out = await reloadxml()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"ok": True, "output": out}
