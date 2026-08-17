"""Relleno sonoro para los silencios del voizbot.

Entre que el paciente termina de hablar y el bot contesta hay un hueco real
(consulta al modelo + síntesis de voz): son 2 a 4 segundos de silencio
absoluto en los que la persona no sabe si la escucharon, si se cayó la
llamada o si le toca repetir. Una recepcionista humana llena ese hueco
tecleando mientras busca en la agenda, y eso mismo es lo que se reproduce
acá: un tecleo suave y discontinuo que comunica "estoy registrando esto".

El audio se sintetiza en vez de traer un archivo: así se controla el nivel
y el timbre para una línea telefónica de 8 kHz (donde no hay agudos por
encima de 4 kHz), y no hay un binario suelto que mantener en el repo. Se
genera una sola vez y queda en disco.
"""

import logging
import math
import random
import struct
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

AMBIENCE_DIR = "ambience"
TYPING_FILE = "tecleo.wav"
FS_SIDE_SOUNDS_DIR = "/usr/share/freeswitch/sounds"

SAMPLE_RATE = 8000
# Suficiente para cubrir hasta el turno más lento del modelo; siempre se
# corta antes, en cuanto la respuesta está lista.
DURATION_SECONDS = 45
# Nivel de fondo: tiene que oírse como algo que pasa en la oficina, no como
# el contenido de la llamada. Medido contra el pico completo (1.0).
PEAK = 0.13
# Semilla fija: el archivo se regenera igual en cualquier despliegue.
SEED = 20260815


def _keystroke(rnd: random.Random) -> list[float]:
    """Una tecla: un "clic" de ruido filtrado sobre un golpe grave corto.
    Las dos componentes juntas son lo que suena a tecla mecánica y no a
    chasquido digital."""
    decay_click = rnd.uniform(0.006, 0.013)
    decay_thump = 0.010
    freq = rnd.uniform(180, 320)
    n = int(rnd.uniform(0.018, 0.038) * SAMPLE_RATE)
    out = []
    for i in range(n):
        t = i / SAMPLE_RATE
        click = (rnd.random() * 2 - 1) * math.exp(-t / decay_click)
        thump = math.sin(2 * math.pi * freq * t) * math.exp(-t / decay_thump)
        out.append(click * 0.75 + thump * 0.35)
    return out


def _render() -> list[float]:
    """Ráfagas de teclas separadas por pausas, como quien escribe palabras
    y se detiene a leer. Un tecleo perfectamente regular delata que es un
    bucle sintético."""
    rnd = random.Random(SEED)
    total = DURATION_SECONDS * SAMPLE_RATE
    buf = [0.0] * total
    pos = 0
    while pos < total:
        for _ in range(rnd.randint(3, 8)):  # una "palabra"
            for i, s in enumerate(_keystroke(rnd)):
                if pos + i < total:
                    buf[pos + i] += s
            pos += int(rnd.uniform(0.080, 0.160) * SAMPLE_RATE)
            if pos >= total:
                break
        # pausa entre palabras, y de vez en cuando una más larga
        pausa = rnd.uniform(0.25, 0.70) if rnd.random() > 0.2 else rnd.uniform(0.8, 1.5)
        pos += int(pausa * SAMPLE_RATE)

    # Paso bajo de un polo: quita la aspereza del ruido crudo, que en 8 kHz
    # sonaría a estática en vez de a teclado.
    y = 0.0
    for i, x in enumerate(buf):
        y += 0.55 * (x - y)
        buf[i] = y

    pico = max((abs(s) for s in buf), default=0.0) or 1.0
    escala = PEAK / pico
    return [s * escala for s in buf]


def _write_wav(path: Path, samples: list[float]) -> None:
    pcm = b"".join(struct.pack("<h", max(-32768, min(32767, int(s * 32767)))) for s in samples)
    byte_rate = SAMPLE_RATE * 2
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, SAMPLE_RATE, byte_rate, 2, 16)
    header += b"data" + struct.pack("<I", len(pcm))
    path.write_bytes(header + pcm)


def ensure_typing_loop() -> str | None:
    """Devuelve la ruta del tecleo TAL COMO LA VE FREESWITCH, generándolo la
    primera vez. Devuelve None si no se pudo: el relleno es un lujo, nunca
    puede tumbar una llamada."""
    try:
        local_dir = Path(settings.fs_sounds_dir) / AMBIENCE_DIR
        local_dir.mkdir(parents=True, exist_ok=True)
        local = local_dir / TYPING_FILE
        if not local.exists() or local.stat().st_size == 0:
            logger.info("Generando el audio de tecleo en %s", local)
            _write_wav(local, _render())
        return f"{FS_SIDE_SOUNDS_DIR}/{AMBIENCE_DIR}/{TYPING_FILE}"
    except Exception:
        logger.exception("No se pudo preparar el audio de tecleo; se seguirá sin relleno")
        return None
