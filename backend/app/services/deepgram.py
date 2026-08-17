"""Deepgram: voz (Aura-2) y transcripción en streaming (Nova-3).

Reemplazo de ElevenLabs para las dos puntas del voizbot. Medido contra el
consumo real: ~$0,0225 por minuto de conversación frente a ~$0,0451 de
ElevenLabs, la mitad, con un solo proveedor y una sola factura.

OJO con el nombre: `deepgram` (voz) no es `deepseek` (el modelo que decide
qué decir). Son dos servicios distintos con nombres parecidos.

La sesión de transcripción expone la MISMA interfaz que
`tts_elevenlabs.ScribeRealtimeSession` —cola `events` con
`partial_transcript` / `committed_transcript`— para que el loop de la
llamada no tenga que saber con qué proveedor está hablando.
"""

import asyncio
import json
import logging
import struct

import httpx
import websockets

logger = logging.getLogger(__name__)

TTS_URL = "https://api.deepgram.com/v1/speak"
STT_URL = "wss://api.deepgram.com/v1/listen"

# Aura-2, voces en español. El nombre del modelo lleva el idioma al final.
SPANISH_VOICES = [
    {"id": "aura-2-celeste-es", "label": "Celeste (mujer, cálida)"},
    {"id": "aura-2-estrella-es", "label": "Estrella (mujer)"},
    {"id": "aura-2-diana-es", "label": "Diana (mujer)"},
    {"id": "aura-2-carina-es", "label": "Carina (mujer)"},
    {"id": "aura-2-selena-es", "label": "Selena (mujer)"},
    {"id": "aura-2-antonia-es", "label": "Antonia (mujer)"},
    {"id": "aura-2-gloria-es", "label": "Gloria (mujer)"},
    {"id": "aura-2-olivia-es", "label": "Olivia (mujer)"},
    {"id": "aura-2-silvia-es", "label": "Silvia (mujer)"},
    {"id": "aura-2-agustina-es", "label": "Agustina (mujer)"},
    {"id": "aura-2-javier-es", "label": "Javier (hombre)"},
    {"id": "aura-2-alvaro-es", "label": "Álvaro (hombre)"},
    {"id": "aura-2-luciano-es", "label": "Luciano (hombre)"},
    {"id": "aura-2-nestor-es", "label": "Néstor (hombre)"},
    {"id": "aura-2-valerio-es", "label": "Valerio (hombre)"},
    {"id": "aura-2-sirio-es", "label": "Sirio (hombre)"},
    {"id": "aura-2-aquila-es", "label": "Aquila (hombre)"},
]

# 16 kHz por la misma razón que en ElevenLabs: bajar de 16000 a los 8000 de
# la línea es una división exacta 2:1, mientras que 24000 (el valor por
# defecto de Deepgram) no lo es y el remuestreo suena mal.
SAMPLE_RATE = 16000


def _wrap_pcm_in_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Cabecera WAV con el tamaño REAL del audio.

    No se usa `container=wav` de Deepgram: como responde en streaming, no
    sabe cuánto va a durar y escribe un tamaño de relleno enorme — medido,
    una frase de 4,5 s venía anunciada como 67.106 segundos. FreeSWITCH
    confía en esa cabecera para saber cuándo termina el archivo, así que
    con ese valor el `playback` no cierra cuando debe y el bot se queda
    colgado en medio del turno. Se pide PCM crudo y se arma la cabecera
    acá, donde el tamaño ya se conoce.
    """
    byte_rate = sample_rate * 2
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, 2, 16)
    header += b"data" + struct.pack("<I", len(pcm))
    return header + pcm


async def list_voices() -> list[dict]:
    return SPANISH_VOICES


async def synthesize(text: str, voice: str, api_key: str) -> bytes:
    """Devuelve un WAV listo para reproducir en la llamada."""
    if not api_key:
        raise ValueError("Falta configurar la API key de Deepgram en Ajustes")
    if not text.strip():
        raise ValueError("El texto no puede estar vacío")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            TTS_URL,
            params={
                "model": voice,
                "encoding": "linear16",
                "sample_rate": SAMPLE_RATE,
                # PCM crudo: la cabecera la ponemos nosotros (ver
                # _wrap_pcm_in_wav — la de Deepgram trae un tamaño ficticio).
                "container": "none",
            },
            headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
            json={"text": text},
        )
    if resp.status_code in (401, 403):
        raise ValueError("API key de Deepgram inválida o sin permisos")
    if resp.status_code >= 400:
        raise ValueError(f"Deepgram rechazó la solicitud ({resp.status_code}): {resp.text[:200]}")
    if not resp.content:
        raise ValueError("No se pudo generar el audio (respuesta vacía de Deepgram)")
    return _wrap_pcm_in_wav(resp.content)


class DeepgramRealtimeSession:
    """Transcripción en vivo con Nova-3.

    A diferencia de ElevenLabs, el audio va como frames BINARIOS crudos y
    no envuelto en JSON+base64: menos trabajo por chunk y menos latencia.

    Traduce los eventos de Deepgram al mismo vocabulario que usa el loop
    de la llamada:
      - resultado provisional (is_final=false)  -> partial_transcript
      - fin de enunciado (speech_final=true)    -> committed_transcript
    """

    def __init__(self, api_key: str, sample_rate: int = 8000, silence_secs: float = 0.7):
        if not api_key:
            raise ValueError("Falta configurar la API key de Deepgram en Ajustes")
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.silence_secs = silence_secs
        self._ws = None
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self._recv_task: asyncio.Task | None = None

    async def __aenter__(self) -> "DeepgramRealtimeSession":
        params = (
            f"?model=nova-3&language=es&encoding=linear16"
            f"&sample_rate={self.sample_rate}&channels=1"
            # interim_results son los parciales que disparan el barge-in.
            f"&interim_results=true&punctuate=true&smart_format=true"
            # endpointing: milisegundos de silencio para cerrar un tramo.
            f"&endpointing={int(self.silence_secs * 1000)}"
            # utterance_end_ms: Deepgram avisa con un evento aparte cuando
            # el turno terminó de verdad. Hace falta porque `speech_final`
            # NO llega de forma fiable — medido contra una llamada real,
            # la mayoría de los tramos cierran con is_final=true y
            # speech_final=false, y esperando solo speech_final el turno
            # no terminaba nunca: el bot saludaba y colgaba a los 15 s
            # dando el turno por vacío.
            f"&utterance_end_ms=1000"
        )
        self._ws = await websockets.connect(
            STT_URL + params, additional_headers={"Authorization": f"Token {self.api_key}"}
        )
        self._recv_task = asyncio.create_task(self._recv_loop())
        return self

    async def _recv_loop(self) -> None:
        # Un turno se arma con varios tramos `is_final`, que van llegando a
        # medida que la persona habla. Se acumulan acá y se entregan juntos
        # cuando el turno cierra, para no mandarle al modelo media frase.
        pendiente: list[str] = []

        async def cerrar_turno() -> None:
            if pendiente:
                await self.events.put({"message_type": "committed_transcript", "text": " ".join(pendiente)})
                pendiente.clear()

        # Red de seguridad además de UtteranceEnd: en una llamada real, un
        # "Sí" de una sola palabra no disparó ni speech_final ni
        # UtteranceEnd — Deepgram se quedó callado del todo, el texto
        # quedó atrapado en `pendiente` y el turno nunca cerró (15s de
        # silencio y cuelgue, sin que el bot llegara a "escuchar" un sí
        # clarísimo). Si hay texto pendiente y pasa más de
        # `utterance_end_ms` sin ningún evento nuevo de Deepgram, se
        # cierra el turno igual acá, sin depender de que avise.
        ws_iter = self._ws.__aiter__()
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(
                        ws_iter.__anext__(), timeout=(self.silence_secs + 0.5) if pendiente else None
                    )
                except asyncio.TimeoutError:
                    await cerrar_turno()
                    continue
                except StopAsyncIteration:
                    break

                try:
                    data = json.loads(raw)
                except (ValueError, TypeError):
                    continue

                tipo = data.get("type")
                # UtteranceEnd: el turno terminó. Es la señal fiable; llega
                # aunque no haya venido ningún speech_final.
                if tipo == "UtteranceEnd":
                    await cerrar_turno()
                    continue
                if tipo != "Results":
                    continue

                alts = (data.get("channel") or {}).get("alternatives") or []
                texto = ((alts[0].get("transcript") if alts else "") or "").strip()
                if not texto:
                    continue

                if data.get("is_final"):
                    pendiente.append(texto)
                    # speech_final sí llega a veces, y cuando llega es un
                    # cierre inmediato: se aprovecha para no esperar el
                    # segundo extra de utterance_end_ms.
                    if data.get("speech_final"):
                        await cerrar_turno()
                else:
                    # Provisional: solo sirve para detectar que la persona
                    # empezó a hablar (barge-in).
                    await self.events.put({"message_type": "partial_transcript", "text": texto})
        except websockets.exceptions.ConnectionClosed as exc:
            logger.warning("Deepgram cerró la conexión: %s", exc)
        finally:
            await cerrar_turno()
            await self.events.put({"message_type": "_closed"})

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if not self._ws or not pcm_bytes:
            return
        await self._ws.send(pcm_bytes)

    async def __aexit__(self, *exc) -> None:
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws:
            try:
                # CloseStream le dice a Deepgram que no espere más audio y
                # cierre limpio en vez de por timeout.
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception:
                pass


async def transcribir_grabacion(audio: bytes, api_key: str) -> list[dict]:
    """Transcribe una grabación completa y separa quién habló.

    `diarize` agrupa por hablante, que es lo que hace legible el resultado:
    sin eso queda un bloque de texto donde no se distingue al bot de la
    persona. Los hablantes vienen numerados (0, 1...) y no siempre en el
    mismo orden, así que se entregan como "hablante N" y es el modelo el
    que deduce quién es quién por el contenido.
    """
    if not api_key:
        raise ValueError("Falta configurar la API key de Deepgram en Ajustes")
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            "https://api.deepgram.com/v1/listen",
            params={
                "model": "nova-3",
                "language": "es",
                "punctuate": "true",
                "diarize": "true",
                "utterances": "true",
            },
            headers={"Authorization": f"Token {api_key}", "Content-Type": "audio/wav"},
            content=audio,
        )
    if resp.status_code in (401, 403):
        raise ValueError("API key de Deepgram inválida o sin permisos")
    if resp.status_code >= 400:
        raise ValueError(f"Deepgram rechazó la transcripción ({resp.status_code}): {resp.text[:200]}")

    datos = resp.json().get("results", {})
    salida = []
    for u in datos.get("utterances", []) or []:
        texto = (u.get("transcript") or "").strip()
        if texto:
            salida.append({
                "rol": f"hablante {u.get('speaker', 0)}",
                "texto": texto,
                "inicio": round(float(u.get("start", 0)), 1),
            })
    return salida
