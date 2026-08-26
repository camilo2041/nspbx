"""Buzón de voz desde el panel: lista, escucha y borra los mensajes de una
extensión. Los mensajes viven en el MISMO volumen que las grabaciones
(voicemail.conf.xml apunta storage-dir a $${recordings_dir}/voicemail), así
que el backend los lee sin tocar el storage interno de FreeSWITCH.

Cada mensaje es msg_XXXX.wav con su metadata en msg_XXXX.txt (líneas
clave=valor: caller_id_number, caller_id_name, date_time, duration…).
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import usuario_actual
from app.core.config import settings
from app.core.database import get_session
from app.core.runtime_settings import runtime_settings
from app.models import User

router = APIRouter(prefix="/api/voicemail", tags=["voicemail"])

# Ruta del buzón: igual que la ve FreeSWITCH, pero montada acá en el backend.
_VM_ROOT = Path(settings.recordings_dir) / "voicemail" / "default" / runtime_settings.fs_domain


def _mbox(ext: str) -> Path:
    return _VM_ROOT / str(ext)


def _meta(txt: Path) -> dict:
    if not txt.exists():
        return {}
    out: dict[str, str] = {}
    for line in txt.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def _mensajes(ext: str) -> list[dict]:
    mbox = _mbox(ext)
    if not mbox.is_dir():
        return []
    out = []
    for f in sorted(mbox.glob("msg_*.wav")):
        m = _meta(f.with_suffix(".txt"))
        fecha = None
        try:
            if m.get("date_time"):
                fecha = datetime.fromtimestamp(int(float(m["date_time"])))
        except (TypeError, ValueError):
            fecha = None
        if fecha is None:
            fecha = datetime.fromtimestamp(f.stat().st_mtime)
        out.append(
            {
                "filename": f.name,
                "caller": m.get("caller_id_name") or m.get("caller_id_number") or "Desconocido",
                "caller_number": m.get("caller_id_number") or "",
                "date": fecha,
                "duration": int(float(m.get("duration", 0) or 0)),
            }
        )
    return out


def _permiso_sobre(ext: str, usuario: User) -> None:
    propia = usuario.extension.number if usuario.extension else None
    if ext != propia and not permissions.puede(usuario.role, permissions.LLAMADAS_VER_TODAS):
        raise HTTPException(status_code=403, detail="No podés ver el buzón de otra extensión")


def _resolver(ext: str, filename: str) -> Path:
    p = (_mbox(ext) / Path(filename).name).resolve()
    base = _mbox(ext).resolve()
    if p.parent != base or not p.name.startswith("msg_") or p.suffix != ".wav" or not p.is_file():
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    return p


@router.get("")
async def list_voicemail(
    extension: str | None = None,
    usuario: User = Depends(usuario_actual),
    session: AsyncSession = Depends(get_session),
):
    ext = extension or (usuario.extension.number if usuario.extension else None)
    if not ext:
        raise HTTPException(status_code=400, detail="Tu usuario no tiene una extensión asignada")
    if extension:
        _permiso_sobre(ext, usuario)
    return {"extension": ext, "messages": _mensajes(ext)}


@router.get("/audio/{ext}/{filename}")
async def voicemail_audio(
    ext: str, filename: str, usuario: User = Depends(usuario_actual), session: AsyncSession = Depends(get_session)
):
    _permiso_sobre(ext, usuario)
    return FileResponse(_resolver(ext, filename), media_type="audio/wav")


@router.delete("/{ext}/{filename}")
async def delete_voicemail(
    ext: str, filename: str, usuario: User = Depends(usuario_actual), session: AsyncSession = Depends(get_session)
):
    _permiso_sobre(ext, usuario)
    p = _resolver(ext, filename)
    p.unlink(missing_ok=True)
    t = p.with_suffix(".txt")
    if t.exists():
        t.unlink()
    return {"ok": True}
