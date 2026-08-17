from pathlib import Path

from app.core.config import settings

BOTS_DIR = "bots"
ALLOWED_EXTENSIONS = {".wav", ".mp3"}

# Ruta que verá FreeSWITCH (freeswitch/sounds está montado ahí como
# /usr/share/freeswitch/sounds), no la ruta local del contenedor del backend.
FS_SIDE_SOUNDS_DIR = "/usr/share/freeswitch/sounds"


def _local_bots_dir() -> Path:
    path = Path(settings.fs_sounds_dir) / BOTS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key(bot_id: int, node_id: str | None) -> str:
    return f"bot_{bot_id}" if not node_id else f"bot_{bot_id}_node_{node_id}"


def save_audio(bot_id: int, filename: str, content: bytes, node_id: str | None = None) -> str:
    """Guarda un audio (saludo del bot, o de un nodo del flujo) y devuelve la
    ruta que FreeSWITCH debe usar para reproducirlo."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Formato no soportado: usa .wav o .mp3")
    key = _key(bot_id, node_id)
    local_path = _local_bots_dir() / f"{key}{ext}"
    for other_ext in ALLOWED_EXTENSIONS - {ext}:
        stale = _local_bots_dir() / f"{key}{other_ext}"
        if stale.exists():
            stale.unlink()
    local_path.write_bytes(content)
    return f"{FS_SIDE_SOUNDS_DIR}/{BOTS_DIR}/{key}{ext}"


def remove_audio(bot_id: int, node_id: str | None = None) -> None:
    key = _key(bot_id, node_id)
    for ext in ALLOWED_EXTENSIONS:
        local_path = _local_bots_dir() / f"{key}{ext}"
        if local_path.exists():
            local_path.unlink()


def remove_all_node_audio(bot_id: int) -> None:
    """Borra todos los audios de nodos de flujo de un bot (al eliminar el bot)."""
    prefix = f"bot_{bot_id}_node_"
    for f in _local_bots_dir().glob(f"{prefix}*"):
        f.unlink()


# Compat: nombres previos usados por el saludo simple del bot (bot.greeting_audio_path).
def save_greeting(bot_id: int, filename: str, content: bytes) -> str:
    return save_audio(bot_id, filename, content)


def remove_greeting(bot_id: int) -> None:
    remove_audio(bot_id)
