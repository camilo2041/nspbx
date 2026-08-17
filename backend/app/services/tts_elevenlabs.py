"""ElevenLabs TTS — voces de mayor calidad, requiere API key propia del
usuario (no gratis). Se usa el modelo multilingüe v2, que soporta español.
"""

import asyncio
import base64
import json
import logging
import struct

import httpx
import websockets

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elevenlabs.io/v1"
REALTIME_STT_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"

# PCM 16 kHz envuelto en WAV, NO el MP3 por defecto de ElevenLabs (44.1 kHz).
# mod_shout no remuestrea bien 44100 -> 8000 (no es ratio entero) y el
# resultado en la llamada es SILENCIO — confirmado con llamadas reales:
# el log decía "done playing file" pero no se oía nada. 16000 -> 8000 es
# 2:1 exacto y el WAV lo reproduce mod_sndfile (nativo, sin mod_shout).
OUTPUT_FORMAT = "pcm_16000"
PCM_SAMPLE_RATE = 16000


def _wrap_pcm_in_wav(pcm: bytes, sample_rate: int = PCM_SAMPLE_RATE) -> bytes:
    """Agrega cabecera WAV a PCM crudo de 16 bits mono."""
    byte_rate = sample_rate * 2
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, 2, 16)
    header += b"data" + struct.pack("<I", len(pcm))
    return header + pcm

# Voces públicas de ElevenLabs conocidas por sonar bien en español con el
# modelo multilingual_v2. El usuario puede tener más voces propias/clonadas
# en su cuenta — list_voices() las trae dinámicamente si hay API key.
DEFAULT_VOICES = [
    {"id": "21m00Tcm4TlvDq8ikWAM", "label": "Rachel (multilingüe, mujer)"},
    {"id": "pNInz6obpgDQGcFmaJgB", "label": "Adam (multilingüe, hombre)"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "label": "Bella (multilingüe, mujer)"},
    {"id": "ErXwobaYiN019PkySvjV", "label": "Antoni (multilingüe, hombre)"},
]


async def list_voices(api_key: str) -> list[dict]:
    """Trae las voces disponibles en la cuenta de ElevenLabs del usuario."""
    if not api_key:
        return DEFAULT_VOICES
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/voices", headers={"xi-api-key": api_key})
    if resp.status_code == 401:
        raise ValueError(
            "ElevenLabs rechazó la API key (401). Revisa que esté bien copiada y que tenga "
            "permiso de 'Voices' habilitado (no solo 'Text to Speech') en elevenlabs.io → API Keys."
        )
    if resp.status_code >= 400:
        raise ValueError(f"ElevenLabs devolvió un error ({resp.status_code}): {resp.text[:200]}")
    voices = resp.json().get("voices", [])
    if not voices:
        return DEFAULT_VOICES
    return [{"id": v["voice_id"], "label": v.get("name", v["voice_id"])} for v in voices]


async def transcribe(audio_bytes: bytes, api_key: str, filename: str = "audio.wav") -> str:
    """Speech-to-text: transcribe un audio grabado del paciente a texto,
    para que el LLM (DeepSeek) pueda entender qué dijo."""
    if not api_key:
        raise ValueError("Falta configurar la API key de ElevenLabs en Ajustes")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/speech-to-text",
            headers={"xi-api-key": api_key},
            # language_code fijo en español: con autodetección, frases
            # cortas o con ruido de línea telefónica se transcribían en
            # otro idioma (confirmado en una llamada real: devolvió texto
            # en telugu para una frase dicha en español).
            data={
                "model_id": "scribe_v1",
                "language_code": "spa",
                # Un solo hablante y sin etiquetas de "eventos de audio":
                # en audio telefónico (8 kHz, con ruido de línea) esas dos
                # opciones metían ruido en la transcripción.
                "num_speakers": "1",
                "tag_audio_events": "false",
            },
            files={"file": (filename, audio_bytes, "audio/wav")},
        )
    if resp.status_code == 401:
        raise ValueError("API key de ElevenLabs inválida")
    if resp.status_code >= 400:
        raise ValueError(f"ElevenLabs STT rechazó la solicitud ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    return (data.get("text") or "").strip()


async def synthesize(text: str, voice_id: str, api_key: str) -> bytes:
    """Devuelve un WAV (PCM 16 kHz) listo para reproducir en la llamada.
    Ver OUTPUT_FORMAT arriba: pedir MP3 daba silencio en el teléfono."""
    if not api_key:
        raise ValueError("Falta configurar la API key de ElevenLabs en Ajustes")
    if not text.strip():
        raise ValueError("El texto no puede estar vacío")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{BASE_URL}/text-to-speech/{voice_id}?output_format={OUTPUT_FORMAT}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                # flash_v2_5 en vez de multilingual_v2: mismo idioma y voz,
                # pero medido 0.89s vs 2.25s para la misma frase — en una
                # conversación telefónica por turnos, esos ~1.4s por
                # respuesta se notan muchísimo.
                "model_id": "eleven_flash_v2_5",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
        )
    if resp.status_code == 401:
        raise ValueError("API key de ElevenLabs inválida o vencida")
    if resp.status_code >= 400:
        raise ValueError(f"ElevenLabs rechazó la solicitud ({resp.status_code}): {resp.text[:200]}")
    if not resp.content:
        raise ValueError("No se pudo generar el audio (respuesta vacía de ElevenLabs)")
    return _wrap_pcm_in_wav(resp.content)


class ScribeRealtimeSession:
    """Sesión de STT en tiempo real (Scribe Realtime v2) para el voizbot IA.

    Reemplaza a transcribe() (archivo completo) en el loop de conversación:
    se le van empujando los frames PCM que llegan de mod_audio_fork y va
    devolviendo transcripciones parciales/confirmadas por el propio
    websocket, en vez de grabar-esperar-transcribir por turnos.

    commit_strategy=vad delega en ElevenLabs la detección de fin de
    enunciado (VAD del lado del servidor) — no hace falta reimplementar
    detección de silencio del lado del backend."""

    def __init__(self, api_key: str, sample_rate: int = 8000, silence_secs: float = 0.7):
        if not api_key:
            raise ValueError("Falta configurar la API key de ElevenLabs en Ajustes")
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.silence_secs = silence_secs
        self._ws: websockets.WebSocketClientProtocol | None = None
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self._recv_task: asyncio.Task | None = None

    async def __aenter__(self) -> "ScribeRealtimeSession":
        # SIN model_id: "scribe_v1" (el modelo del STT REST normal) no es
        # válido para este endpoint realtime — el servidor aceptaba el
        # connect pero cerraba con 1008 invalid_request apenas llegaba el
        # primer chunk de audio, sin más detalle. Confirmado probando en
        # aislado: omitiendo model_id (o con "scribe_v2_realtime") el
        # servidor responde "session_started" normalmente.
        url = (
            f"{REALTIME_STT_URL}?language_code=es"
            f"&audio_format=pcm_{self.sample_rate}&commit_strategy=vad"
            f"&vad_silence_threshold_secs={self.silence_secs}"
        )
        self._ws = await websockets.connect(url, additional_headers={"xi-api-key": self.api_key})
        self._recv_task = asyncio.create_task(self._recv_loop())
        return self

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                logger.info("Scribe Realtime recv: %s", raw[:500])
                try:
                    await self.events.put(json.loads(raw))
                except (ValueError, TypeError):
                    continue
        except websockets.exceptions.ConnectionClosed as exc:
            logger.warning("Scribe Realtime cerró la conexión: %s", exc)
        finally:
            await self.events.put({"message_type": "_closed"})

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if not self._ws or not pcm_bytes:
            return
        await self._ws.send(json.dumps({
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(pcm_bytes).decode("ascii"),
            "sample_rate": self.sample_rate,
            # Obligatorio en el esquema de ElevenLabs (aunque no lo usemos:
            # el commit real lo decide el VAD del servidor vía
            # commit_strategy=vad en la URL). Sin este campo el server
            # cierra el socket con 1008 policy violation / invalid_request.
            "commit": False,
        }))

    async def __aexit__(self, *exc) -> None:
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
