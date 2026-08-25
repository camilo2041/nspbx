from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as env_settings
from app.core.database import get_session
from app.core.runtime_settings import runtime_settings
from app.models import SystemSettings
from app.schemas import HoldMusicUpdate, SystemSettingsOut, SystemSettingsUpdate
from app.services import esl

router = APIRouter(prefix="/api/system", tags=["system"])


async def get_or_create_settings(session: AsyncSession) -> SystemSettings:
    row = await session.get(SystemSettings, 1)
    if not row:
        # Semilla inicial desde las variables de entorno del contenedor
        # (docker-compose), no desde los defaults estáticos del modelo.
        row = SystemSettings(
            id=1,
            app_name=env_settings.app_name,
            fs_domain=env_settings.fs_domain,
            fs_esl_host=env_settings.fs_esl_host,
            fs_esl_port=env_settings.fs_esl_port,
            fs_esl_password=env_settings.fs_esl_password,
            fs_http_base=env_settings.fs_http_base,
            sip_ws_url=env_settings.sip_ws_url,
            sip_server_ip=env_settings.sip_server_ip,
            sip_server_port=env_settings.sip_server_port,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def apply_to_runtime(row: SystemSettings):
    runtime_settings.app_name = row.app_name
    runtime_settings.fs_domain = row.fs_domain
    runtime_settings.fs_esl_host = row.fs_esl_host
    runtime_settings.fs_esl_port = row.fs_esl_port
    runtime_settings.fs_esl_password = row.fs_esl_password
    runtime_settings.fs_http_base = row.fs_http_base


# --- Música de espera (MOH) ---------------------------------------------
# Carpeta con las pistas que toca local_stream (ver local_stream.conf.xml:
# el stream "moh/8000" apunta a $${sounds_dir}/music/8000). El backend la
# tiene montada en FS_SOUNDS_DIR con el MISMO contenido que
# /usr/share/freeswitch/sounds del contenedor de FreeSWITCH.
MUSIC_DIR = Path(env_settings.fs_sounds_dir) / "music" / "8000"
HOLD_ALEATORIO = "local_stream://moh"


def _hold_estado(row: SystemSettings) -> dict:
    """Lee el valor persistido y lo traduce a (mode, file) para el panel."""
    valor = (row.hold_music or HOLD_ALEATORIO).strip()
    if valor == HOLD_ALEATORIO:
        return {"mode": "random", "file": None}
    return {"mode": "file", "file": valor.rsplit("/", 1)[-1] or None}


def _listar_pistas() -> list[dict]:
    if not MUSIC_DIR.is_dir():
        return []
    out = []
    for p in sorted(MUSIC_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in (".wav", ".mp3"):
            out.append({"name": p.name, "size": p.stat().st_size})
    return out


def _resolver_pista(nombre: str) -> Path:
    """Valida que `nombre` sea una pista existente dentro de MUSIC_DIR (sin
    permitir traversal: se descarta cualquier cosa que no sea un basename)."""
    base = Path(nombre or "").name
    destino = (MUSIC_DIR / base).resolve()
    if base != nombre or destino.parent != MUSIC_DIR.resolve() or not destino.is_file():
        raise HTTPException(status_code=404, detail="Pista no encontrada")
    return destino


async def aplicar_hold_en_vivo(valor: str) -> None:
    """Aplica la música de espera a FreeSWITCH con global_setvar: las
    variables globales se copian a cada canal NUEVO, así el cambio vale para
    las próximas llamadas sin reiniciar. Si FreeSWITCH no está disponible se
    ignora — el valor queda persistido y se aplica en el próximo arranque
    (ver main.py lifespan)."""
    try:
        await esl.api(f"global_setvar hold_music={valor}")
    except Exception:
        pass


@router.get("/hold-music")
async def get_hold_music(session: AsyncSession = Depends(get_session)):
    row = await get_or_create_settings(session)
    return {"estado": _hold_estado(row), "files": _listar_pistas()}


@router.put("/hold-music")
async def set_hold_music(payload: HoldMusicUpdate, session: AsyncSession = Depends(get_session)):
    if payload.mode not in ("random", "file"):
        raise HTTPException(status_code=400, detail="mode debe ser 'random' o 'file'")
    if payload.mode == "file":
        pista = _resolver_pista(payload.file or "")
        valor = f"{HOLD_ALEATORIO}/8000/{pista.name}"
    else:
        valor = HOLD_ALEATORIO
    row = await get_or_create_settings(session)
    row.hold_music = valor
    await session.commit()
    await session.refresh(row)
    await aplicar_hold_en_vivo(valor)
    return {"estado": _hold_estado(row), "files": _listar_pistas()}


@router.post("/hold-music/upload")
async def upload_hold_music(file: UploadFile):
    nombre = Path(file.filename or "pista.wav").name
    if Path(nombre).suffix.lower() not in (".wav", ".mp3"):
        raise HTTPException(status_code=400, detail="Solo archivos WAV o MP3")
    contenido = await file.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    if len(contenido) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="El archivo supera los 25 MB")
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    destino = MUSIC_DIR / nombre
    destino.write_bytes(contenido)
    return {"name": destino.name, "size": destino.stat().st_size}


@router.delete("/hold-music/{filename}")
async def delete_hold_music(filename: str, session: AsyncSession = Depends(get_session)):
    destino = _resolver_pista(filename)
    destino.unlink()
    # Si se borró la pista que estaba en uso, se vuelve al modo aleatorio
    # para que la música de espera no quede apuntando a un archivo inexistente.
    row = await get_or_create_settings(session)
    if _hold_estado(row).get("file") == destino.name:
        row.hold_music = HOLD_ALEATORIO
        await session.commit()
        await aplicar_hold_en_vivo(HOLD_ALEATORIO)
    return {"ok": True}


@router.get("/hold-music/audio/{filename}")
async def hold_music_audio(filename: str):
    """Sirve la pista para escucharla en el panel. Va por api.getBlob en el
    front (manda el token); un <audio src> nativo no podría autenticarse."""
    destino = _resolver_pista(filename)
    media = "audio/mpeg" if destino.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(destino, media_type=media)


@router.get("/settings", response_model=SystemSettingsOut)
async def get_settings(session: AsyncSession = Depends(get_session)):
    return await get_or_create_settings(session)


@router.put("/settings", response_model=SystemSettingsOut)
async def update_settings(
    payload: SystemSettingsUpdate, session: AsyncSession = Depends(get_session)
):
    row = await get_or_create_settings(session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
    apply_to_runtime(row)
    await esl.invalidate_client()
    return row
