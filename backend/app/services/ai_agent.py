"""Voizbot conversacional en tiempo real: FreeSWITCH entrega el control de
la llamada a este servidor (ESL "outbound socket" mode, ver dialplan
`socket backend:8085 async full`), que a su vez arranca `mod_audio_fork`
sobre ese mismo canal para streamear el audio del paciente en vivo.

Pipeline: mod_audio_fork -> /ws/voicebot/{call_id} (este proceso) -> STT
streaming (ElevenLabs Scribe Realtime) -> DeepSeek (decide qué decir/hacer)
-> TTS por frase -> playback nativo de FreeSWITCH, interrumpible con
`uuid_break` si el paciente empieza a hablar mientras el bot responde
(barge-in). Ver AGENT_SYSTEM_PROMPT para el guion.
"""

import asyncio
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.exc import IntegrityError

from app.core.clock import fecha_en_palabras, hora_en_palabras, now_local
from app.core.config import settings
from app.core.database import async_session
from app.models import Appointment, SystemSettings
from app.services import ai_node, ambience, deepgram, llm, tts, tts_elevenlabs
from app.services.usage import UsageMeter
from app.services.appointments import (
    available_slots,
    business_hours_error,
    find_next_appointment,
    is_slot_free,
    parse_date,
    parse_time,
)

logger = logging.getLogger(__name__)

AI_SESSIONS_DIR = "ai_sessions"
FS_SIDE_SOUNDS_DIR = "/usr/share/freeswitch/sounds"
MAX_TURNS = 12
# Cuánto esperar en silencio a que el paciente empiece a hablar antes de
# dar el turno por vacío y colgar (reemplaza al viejo RECORD_TIME_LIMIT +
# umbral de energía: ahora el fin de turno lo decide el VAD del propio
# Scribe Realtime, del lado del servidor, no un temporizador fijo local).
TURN_TIMEOUT_SECONDS = 15
# Segundos de silencio que Scribe espera antes de dar por "confirmado" (fin
# de enunciado) un tramo de habla — equivalente al viejo RECORD_SILENCE_HITS,
# pero evaluado en tiempo real sobre el audio, no como corte de grabación.
VAD_SILENCE_SECS = 0.7
# "Alice" (premade): confirmada usable en plan free. NO usar
# tts_elevenlabs.DEFAULT_VOICES[0] (Rachel) — es una voz de librería
# compartida bloqueada por API en plan free (402 payment_required).
VOICE_ID = "Xb7hH8MSUJpSbSDYk0k2"

def _local_sessions_dir() -> Path:
    path = Path(settings.fs_sounds_dir) / AI_SESSIONS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


class ESLOutboundSession:
    """Conexión ESL en modo "outbound" (FreeSWITCH conecta HACIA nosotros)
    para UNA llamada. Protocolo mínimo: `connect` para recibir las
    variables del canal, `sendmsg ... event-lock: true` para ejecutar
    aplicaciones de forma bloqueante, y `api` para comandos de una sola
    respuesta (uuid_audio_fork, uuid_break)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.channel_vars: dict[str, str] = {}

    async def _read_message(self) -> tuple[dict, str]:
        headers: dict = {}
        while True:
            line = await self.reader.readline()
            if not line:
                raise ConnectionError("Conexión ESL cerrada por FreeSWITCH")
            decoded = line.decode(errors="replace").rstrip("\r\n")
            if not decoded:
                break
            if ":" in decoded:
                k, _, v = decoded.partition(":")
                headers[k.strip().lower()] = v.strip()
        length = int(headers.get("content-length", 0) or 0)
        body = ""
        if length > 0:
            body = (await self.reader.readexactly(length)).decode(errors="replace")
        return headers, body

    async def connect(self) -> None:
        self.writer.write(b"connect\n\n")
        await self.writer.drain()
        headers, _ = await self._read_message()
        self.channel_vars = headers
        # Suscribirse a los eventos de ESTE canal. Sin esto no hay forma de
        # saber cuándo termina de verdad cada aplicación: `sendmsg` responde
        # "+OK" apenas ENCOLA el comando, no cuando la app finaliza
        # (confirmado en una llamada real: `record` arrancó 20 ms ANTES de
        # que terminara el beep de 200 ms que lo precedía).
        self.writer.write(b"myevents plain\n\n")
        await self.writer.drain()
        await self._read_message()

    @staticmethod
    def _parse_event(body: str) -> dict:
        event: dict = {}
        for line in body.split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                event[k.strip().lower()] = v.strip()
        return event

    async def execute(self, app: str, arg: str = "", timeout: float = 60.0) -> None:
        """Ejecuta una app y ESPERA a que termine (CHANNEL_EXECUTE_COMPLETE)."""
        msg = (
            "sendmsg\n"
            "call-command: execute\n"
            f"execute-app-name: {app}\n"
            f"execute-app-arg: {arg}\n"
            "event-lock: true\n"
            "\n"
        )
        self.writer.write(msg.encode())
        await self.writer.drain()
        await self._read_message()  # "+OK" de encolado, NO de finalización

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                headers, body = await asyncio.wait_for(
                    self._read_message(), timeout=max(1.0, deadline - loop.time())
                )
            except asyncio.TimeoutError:
                return
            if headers.get("content-type") != "text/event-plain":
                continue
            event = self._parse_event(body)
            name = event.get("event-name")
            if name == "CHANNEL_EXECUTE_COMPLETE" and event.get("application") == app:
                return
            if name in ("CHANNEL_HANGUP", "CHANNEL_HANGUP_COMPLETE", "CHANNEL_DESTROY"):
                raise ConnectionError("La llamada fue colgada")

    async def api(self, command: str) -> str:
        """Comando `api` de una sola respuesta (no bloquea a que termine una
        app del canal, solo a que FreeSWITCH ejecute el comando en sí —
        usado para uuid_audio_fork y uuid_break)."""
        self.writer.write(f"api {command}\n\n".encode())
        await self.writer.drain()
        while True:
            headers, body = await self._read_message()
            if headers.get("content-type") == "api/response":
                return body

    async def hangup(self) -> None:
        try:
            self.writer.write(b"api uuid_kill " + self.channel_vars.get("unique-id", "").encode() + b"\n\n")
            await self.writer.drain()
        except Exception:
            pass
        self.writer.close()


# Herramientas que MODIFICAN la agenda (no solo consultan).
_TOOLS_QUE_MODIFICAN = ("agendar_cita", "cancelar_cita", "reagendar_cita", "confirmar_cita")
# Palabras con las que el modelo da por hecha una acción.
_AFIRMACIONES = ("cancelad", "agendad", "reagendad", "confirmad")

# Detecta que la respuesta le está proponiendo horarios a la persona:
# "a las 10:00", "a las tres de la tarde", "a las once y media".
_HORAS = re.compile(
    r"\b\d{1,2}:\d{2}\b"
    r"|\ba\s+las\s+(?:una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|\d{1,2})\b",
    re.IGNORECASE,
)


async def _llm_turn(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    caller_phone: str,
    meter: UsageMeter,
    tools: list[dict] | None = None,
    appointment_id_fijo: int | None = None,
    exits: dict[str, str] | None = None,
) -> tuple[str, bool, str | None]:
    """Le pasa la conversación al modelo de lenguaje configurado en
    Ajustes, ejecuta las tool calls que pida (contra la agenda real), y
    devuelve (texto_para_decir, terminar_turno, nodo_siguiente).

    `terminar_turno` corta el loop de turnos de ESTE nodo — por
    `terminar_llamada` (cuelga) o por `avanzar_flujo` (salta a
    `nodo_siguiente` en vez de colgar, ver ai_agent.handle_call)."""
    should_end = False
    next_node_id: str | None = None
    reply_text = ""
    hubo_accion = False
    ya_se_reclamo = False
    # ¿Se consultó la agenda en este turno? Si el bot va a nombrar
    # horarios, tienen que salir de una consulta y no de su imaginación.
    hubo_consulta = False
    ya_se_reclamo_horarios = False

    for _ in range(5):  # tope de vueltas tool-call -> tool-call por turno
        message, uso = await llm.chat(base_url, model, api_key, messages, tools=tools)
        meter.llm(uso)
        messages.append(message)
        calls = llm.parse_tool_calls(message)

        if not calls:
            reply_text = message.get("content") or ""
            # Guarda anti-alucinación: el modelo a veces AFIRMA haber hecho
            # la acción sin llegar a llamar la herramienta. Pasó en una
            # llamada real: dijo "Tu cita ha sido cancelada" y la cita
            # seguía activa en la base. Si dice que hizo algo pero no
            # ejecutó ninguna herramienta que modifique, se le exige.
            if (
                not hubo_accion
                and not ya_se_reclamo
                and any(p in reply_text.lower() for p in _AFIRMACIONES)
            ):
                ya_se_reclamo = True
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "No ejecutaste ninguna herramienta, así que en la agenda NO cambió nada. "
                            "Si la persona ya confirmó, llama AHORA a la herramienta que corresponda "
                            "(agendar_cita / cancelar_cita / reagendar_cita). Si todavía falta algún "
                            "dato, pídeselo — pero no afirmes que la acción está hecha."
                        ),
                    }
                )
                continue

            # Guarda anti-invención de horarios. En una llamada real el bot
            # ofreció "las tres de la tarde" sin haber consultado, y esa
            # hora estaba ocupada: al intentar agendarla tuvo que
            # retractarse y la persona respondió "ya te había confirmado
            # que a las tres". Prometer un cupo que no existe es peor que
            # demorarse un segundo en mirarlo.
            if (
                not hubo_consulta
                and not ya_se_reclamo_horarios
                and _HORAS.search(reply_text)
            ):
                ya_se_reclamo_horarios = True
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Estás nombrando horarios sin haber consultado la agenda en este turno. "
                            "Llama AHORA a consultar_disponibilidad para ese día y ofrece solo "
                            "horarios que aparezcan en el resultado. No inventes ni supongas cupos."
                        ),
                    }
                )
                continue
            break

        async with async_session() as session:
            for call_id, name, args in calls:
                ok, result, info = await _run_tool(session, name, args, caller_phone, appointment_id_fijo, exits)
                if name == "terminar_llamada":
                    should_end = True
                if name == "avanzar_flujo" and ok and info:
                    next_node_id = info.get("avanzar_a")
                    should_end = True
                if name == "consultar_disponibilidad":
                    hubo_consulta = True
                if name in _TOOLS_QUE_MODIFICAN and ok:
                    hubo_accion = True
                    # La llamada dejó algo hecho en la agenda: es lo que
                    # separa una conversación resuelta de una que solo gastó.
                    meter.resolved = True
                    if info:
                        meter.action = info["action"]
                        meter.appointment_id = info["appointment_id"]
                        meter.action_appointment_date = info["appointment_date"]
                        meter.action_patient_name = info["patient_name"]
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result})

    # Si se agotaron las vueltas y el modelo nunca llegó a redactar una
    # respuesta, el bot se quedaba MUDO: handle_call salta el playback
    # (está guardado por `if reply_text`), espera el turno en silencio y
    # cuelga. Acá se le fuerza una última respuesta solo-texto.
    #
    # Esto también pasa (y es peor) cuando el modelo YA llamó a
    # terminar_llamada: en una llamada real, el modelo llamó a
    # confirmar_cita y terminar_llamada juntas, sin texto — colgó sin
    # despedirse. Antes esto se saltaba (`and not should_end`) porque se
    # pensaba solo en "el turno sigue, que no quede en silencio"; pero un
    # silencio en medio de la llamada al menos deja el turno abierto para
    # que la persona hable de nuevo, mientras que colgar sin decir nada
    # no tiene forma de recuperarse.
    if not reply_text:
        try:
            message, uso = await llm.chat(base_url, model, api_key, messages, tool_choice="none", tools=tools)
            meter.llm(uso)
            messages.append(message)
            reply_text = message.get("content") or ""
        except Exception:
            logger.exception("No se pudo forzar la respuesta final del modelo")

    # Último recurso: nunca terminar el turno (ni menos aún colgar) sin
    # decir nada. Un silencio seco y cuelgue es peor que una frase de
    # relleno o de cierre.
    if not reply_text:
        # Genérico y no específico de "confirmar" — este último recurso
        # se comparte con reagendar/cancelar/agendar, así que no puede
        # asumir qué pasó en la llamada (cada gestión ya trae su propio
        # cierre cálido en su `objetivo`; esto solo cubre que el modelo
        # nunca haya llegado a decir nada).
        reply_text = (
            "¡Muchas gracias por tu tiempo! Que tengas buen día."
            if should_end
            else "Perdóname, se me enredó un momento. ¿Me repites lo último, por favor?"
        )

    return reply_text, should_end, next_node_id


async def _buscar_cita(session, caller_phone: str, appointment_id: int | None):
    """Si la llamada trae una cita fijada (campaña, ver
    nspbx_appointment_id), se actúa sobre ESA exactamente. Si no, se cae
    al criterio de siempre (la próxima confirmada de este teléfono) —
    necesario para llamadas entrantes normales, que nunca traen una cita
    fijada de antemano."""
    if appointment_id:
        appt = await session.get(Appointment, appointment_id)
        if appt:
            return appt
    return await find_next_appointment(session, caller_phone)


def _info_accion(accion: str, appt) -> dict:
    return {
        "action": accion,
        "appointment_id": appt.id,
        "appointment_date": appt.appointment_date,
        "patient_name": appt.patient_name,
    }


async def _run_tool(
    session,
    name: str,
    args: dict,
    caller_phone: str,
    appointment_id: int | None = None,
    exits: dict[str, str] | None = None,
) -> tuple[bool, str, dict | None]:
    """Devuelve (funcionó, mensaje para el modelo, info de la acción o
    None). `info` es lo que necesita el registro de gestión (ver
    AiCallUsage) — solo se llena cuando la herramienta de verdad
    modificó una cita.

    El éxito se declara explícitamente y NO se deduce del texto. Antes se
    miraba si el mensaje contenía la palabra "error", y ninguno de los
    siete rechazos por regla de negocio la contiene ("Ese horario ya está
    ocupado", "No encontré una cita para cancelar", "El consultorio no
    atiende los domingos"…): todos contaban como gestión hecha. Eso
    inflaba la tasa de contención y, peor, desarmaba la guarda
    anti-alucinación, que se apaga cuando cree que ya hubo una acción."""
    try:
        if name == "consultar_disponibilidad":
            d = parse_date(args["date"])
            slots = await available_slots(session, d)
            # Todas las herramientas nombran el día de la semana además de
            # la fecha: si el modelo pidió el 18 cuando el paciente dijo
            # "viernes", ve "martes 18" en la respuesta y puede corregirse
            # antes de confirmarle algo equivocado.
            cuando = fecha_en_palabras(d)
            if not slots:
                return False, f"No hay horarios libres el {cuando}.", None
            return True, f"Horarios libres el {cuando}: {', '.join(slots)}", None

        if name == "agendar_cita":
            from datetime import datetime as dt

            start = dt.combine(parse_date(args["date"]), parse_time(args["time"]))
            motivo = business_hours_error(start, 30)
            if motivo:
                return False, f"{motivo} Ofrécele otro horario.", None
            if not await is_slot_free(session, start, 30):
                return False, "Ese horario ya está ocupado.", None
            appt = Appointment(patient_name=args["patient_name"], phone=caller_phone, appointment_date=start, status="confirmed")
            session.add(appt)
            try:
                await session.commit()
            except IntegrityError:
                # Otra llamada simultánea ganó el mismo hueco entre el
                # chequeo y el insert (ver el índice ux_appointments_slot).
                await session.rollback()
                return False, "Ese horario acaba de ocuparse. Ofrécele otro.", None
            return (
                True,
                f"Cita agendada para el {fecha_en_palabras(start.date())} a las {start.strftime('%H:%M')}.",
                _info_accion("agendada", appt),
            )

        if name == "confirmar_cita":
            appt = await _buscar_cita(session, caller_phone, appointment_id)
            if not appt:
                return False, "No encontré una cita para confirmar.", None
            cuando = f"{fecha_en_palabras(appt.appointment_date.date())} a las {hora_en_palabras(appt.appointment_date)}"
            appt.confirmed_at = now_local()
            await session.commit()
            return True, f"Cita del {cuando} confirmada por el paciente.", _info_accion("confirmada", appt)

        if name == "cancelar_cita":
            appt = await _buscar_cita(session, caller_phone, appointment_id)
            if not appt:
                return False, "No encontré una cita para cancelar.", None
            cuando = f"{fecha_en_palabras(appt.appointment_date.date())} a las {appt.appointment_date.strftime('%H:%M')}"
            appt.status = "cancelled"
            await session.commit()
            return True, f"Cita del {cuando} cancelada.", _info_accion("cancelada", appt)

        if name == "reagendar_cita":
            from datetime import datetime as dt

            appt = await _buscar_cita(session, caller_phone, appointment_id)
            if not appt:
                return False, "No encontré una cita para reagendar.", None
            new_start = dt.combine(parse_date(args["new_date"]), parse_time(args["new_time"]))
            motivo = business_hours_error(new_start, appt.duration_minutes)
            if motivo:
                return False, f"{motivo} Ofrécele otro horario.", None
            if not await is_slot_free(session, new_start, appt.duration_minutes):
                return False, "Ese nuevo horario ya está ocupado.", None
            appt.appointment_date = new_start
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False, "Ese horario acaba de ocuparse. Ofrécele otro.", None
            return (
                True,
                f"Cita reagendada para el {fecha_en_palabras(new_start.date())} a las {new_start.strftime('%H:%M')}.",
                _info_accion("reagendada", appt),
            )

        if name == "terminar_llamada":
            return True, "Llamada finalizada.", None

        if name == "avanzar_flujo":
            # El enum de `razon` ya viene acotado por llm.tools_para a las
            # salidas configuradas de ESTE nodo (ver ai_node.py), así que
            # un `target` ausente acá sería el modelo inventando una razón
            # fuera del enum — no debería pasar, pero no hay de dónde
            # saltar si pasa.
            razon = str(args.get("razon", "")).strip()
            target = (exits or {}).get(razon)
            if not target:
                return False, "Esa salida no existe en este punto del flujo.", None
            return True, "Avanzando al siguiente punto del flujo.", {"avanzar_a": target}
    except Exception as exc:
        logger.exception("Error ejecutando tool %s", name)
        return False, f"Ocurrió un error interno: {exc}", None
    return False, "Herramienta desconocida.", None


class ThinkingSound:
    """El tecleo que rellena el silencio mientras el bot consulta.

    Va con `uuid_broadcast` y no con `playback`: broadcast no bloquea, así
    que el loop puede consultar al modelo y sintetizar la voz mientras el
    sonido corre, y se corta con `uuid_break` en cuanto hay algo que decir.
    Con `playback` (que sí espera a terminar) el relleno retrasaría
    justamente la respuesta que está tapando."""

    def __init__(self, session: ESLOutboundSession, path: str | None):
        self.session = session
        self.path = path
        self._sonando = False

    async def start(self) -> None:
        if self._sonando or not self.path:
            return
        self._sonando = True
        uid = self.session.channel_vars.get("unique-id", "")
        try:
            await self.session.api(f"uuid_broadcast {uid} {self.path} aleg")
        except Exception:
            # El relleno es un adorno: si falla, la llamada sigue en silencio
            # como antes, pero sigue.
            self._sonando = False
            logger.warning("No se pudo arrancar el tecleo de fondo")

    async def stop(self) -> None:
        """Idempotente: se llama sin miedo desde varios puntos del turno."""
        if not self._sonando:
            return
        self._sonando = False
        uid = self.session.channel_vars.get("unique-id", "")
        try:
            await self.session.api(f"uuid_break {uid} all")
        except Exception:
            pass


class CallBridge:
    """Puente entre la sesión ESL outbound (que controla la llamada) y el
    websocket de audio (que recibe el stream de mod_audio_fork). Vive
    mientras dura la llamada, indexado por call_id en `active_bridges`."""

    def __init__(self, scribe: tts_elevenlabs.ScribeRealtimeSession, meter: UsageMeter):
        self.scribe = scribe
        self.meter = meter
        self.utterances: asyncio.Queue[str | None] = asyncio.Queue()
        # Se activa con CUALQUIER transcripción parcial — señal de que el
        # paciente está hablando, usada para el barge-in mientras el bot
        # reproduce su respuesta.
        self.speech_detected = asyncio.Event()


active_bridges: dict[str, CallBridge] = {}

router = APIRouter()


async def _saltar_a_nodo(session: ESLOutboundSession, bot_id: str, node_id: str) -> None:
    """`avanzar_flujo` decidió seguir la llamada en otro nodo del mismo
    flujo, en vez de colgar. Para el audio-fork de este tramo (si no,
    quedaría corriendo dos veces sobre el mismo canal) y transfiere el
    canal al contexto de dialplan de ese nodo — mismo `uuid`, la llamada
    sigue viva. Si el nodo destino también es un Agente IA, su contexto
    (ver flow_engine._build_ai_agent_context) vuelve a hacer `socket`, así
    que FreeSWITCH abre una sesión ESL outbound NUEVA e independiente para
    él: handle_call se invoca de nuevo para el mismo call_id, con su
    propio prompt/mensajes desde cero. Mecanismo nuevo, sin probar todavía
    contra una llamada real — confirmarlo antes de confiar en él para
    tráfico de producción."""
    uid = session.channel_vars.get("unique-id", "")
    try:
        await session.api(f"uuid_audio_fork {uid} stop voizbot")
    except Exception:
        pass
    context_name = f"bot_{bot_id}_n{node_id}"
    await session.execute("transfer", f"{context_name} XML {context_name}")


@router.websocket("/ws/voicebot/{call_id}")
async def voicebot_audio_ws(websocket: WebSocket, call_id: str) -> None:
    """Recibe el audio del canal que manda mod_audio_fork (PCM L16, 8kHz,
    mono) y lo reenvía al STT streaming de ElevenLabs. El primer mensaje que
    manda el módulo es un frame de TEXTO con la metadata que le pasamos en
    `uuid_audio_fork ... start`; de ahí en más son frames binarios de audio."""
    await websocket.accept()
    bridge = active_bridges.get(call_id)
    if bridge is None:
        logger.warning("Voizbot IA: llegó audio de %s sin sesión activa, cerrando websocket", call_id)
        await websocket.close()
        return
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                try:
                    bridge.meter.stt(len(message["bytes"]))
                    await bridge.scribe.send_audio(message["bytes"])
                except Exception:
                    # Si el websocket de Scribe se cayó (blip de red, etc.),
                    # que no reviente TODO el forwarding de audio de golpe:
                    # _consume_transcripts ya recibe el sentinel "_closed" y
                    # cuelga la llamada limpio por su cuenta (ver
                    # handle_call). Acá solo se loguea una vez y se corta
                    # este loop, sin traceback ruidoso repetido por chunk.
                    logger.warning("Voizbot IA: se perdió el STT streaming de %s", call_id)
                    break
            # el resto (texto: metadata inicial de mod_audio_fork) no aporta nada acá
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Voizbot IA: error en websocket de audio de %s", call_id)


# Umbral mínimo de texto para considerar un partial_transcript como habla
# real del paciente. En una llamada real por troncal PSTN sin cancelación
# de eco, la propia voz del bot se filtra de vuelta en el audio que
# mod_audio_fork captura del "caller" y Scribe la transcribe como
# fragmentos cortos y sin sentido — eso disparaba barge-in contra sí mismo
# (el bot se cortaba y arrancaba una respuesta con basura). Exigir un
# mínimo de caracteres filtra ese ruido de eco sin perder interrupciones
# reales (una persona interrumpiendo dice más que un par de letras).
_MIN_BARGEIN_CHARS = 4


async def _consume_transcripts(bridge: CallBridge) -> None:
    """Tarea de fondo: clasifica los eventos de Scribe Realtime en
    "el paciente está hablando" (barge-in) y "turno completo" (utterance)."""
    while True:
        event = await bridge.scribe.events.get()
        mtype = event.get("message_type")
        if mtype == "partial_transcript" and len((event.get("text") or "").strip()) >= _MIN_BARGEIN_CHARS:
            bridge.speech_detected.set()
        elif mtype in ("committed_transcript", "committed_transcript_with_timestamps"):
            text = (event.get("text") or "").strip()
            if text:
                await bridge.utterances.put(text)
        elif mtype == "_closed":
            await bridge.utterances.put(None)
            return


async def _wait_utterance(bridge: CallBridge, timeout: float) -> str | None:
    try:
        return await asyncio.wait_for(bridge.utterances.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def _play_sentence(session: ESLOutboundSession, path: str, bridge: CallBridge) -> bool:
    """Reproduce una frase, cortándola con `uuid_break` en cuanto el
    paciente empieza a hablar de vuelta (barge-in). Devuelve True si hubo
    interrupción."""
    uid = session.channel_vars.get("unique-id", "")
    bridge.speech_detected.clear()
    play_task = asyncio.create_task(session.execute("playback", path))

    # Período de gracia: ignorar barge-in en los primeros ~400ms de cada
    # frase (sin dejar de reproducir). La cola de audio del eco de línea
    # (ver _MIN_BARGEIN_CHARS) tiende a filtrarse justo al arrancar el
    # nuevo playback, encima de la respuesta anterior — confirmado en una
    # llamada real por troncal PSTN. shield() evita que el timeout del
    # wait_for cancele play_task; si la frase es más corta que el período
    # de gracia, play_task ya habrá terminado normal para acá.
    try:
        await asyncio.wait_for(asyncio.shield(play_task), timeout=0.4)
    except asyncio.TimeoutError:
        pass
    except Exception:
        pass  # se re-lanza más abajo al hacer `await play_task`

    bridge.speech_detected.clear()
    if play_task.done():
        await play_task  # deja que se propague cualquier excepción real (p.ej. colgó)
        return False

    watch_task = asyncio.create_task(bridge.speech_detected.wait())
    await asyncio.wait({play_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)

    if watch_task.done() and not play_task.done():
        # CRÍTICO: hay que dejar de leer del stream ESL con play_task ANTES
        # de que session.api() lea su respuesta — dos corutinas leyendo el
        # mismo StreamReader a la vez revienta con "readuntil() called
        # while another coroutine is already waiting for incoming data"
        # (confirmado con una llamada real). Cancelar play_task solo corta
        # NUESTRA lectura de sus eventos; el audio en el teléfono lo corta
        # uuid_break.
        play_task.cancel()
        try:
            await play_task
        except (asyncio.CancelledError, Exception):
            pass
        await session.api(f"uuid_break {uid} all")
        return True

    watch_task.cancel()
    try:
        await watch_task
    except asyncio.CancelledError:
        pass
    await play_task  # deja que se propague cualquier excepción real (p.ej. colgó)
    return False


# Tope de caracteres del PRIMER trozo que se sintetiza. Solo ese manda en
# el silencio que percibe el paciente: mientras suena, los siguientes se
# van generando por detrás. Con Deepgram la síntesis tarda ~25 ms por
# carácter (medido: 18 car → 1,1 s; 200 car → 5,3 s), así que una primera
# frase larga se traduce en varios segundos de nada antes de que el bot
# abra la boca. 60 caracteres ≈ 1,5 s de espera.
_MAX_PRIMER_TROZO = 60


def _con_variables(texto: str, cita) -> str:
    """Reemplaza {cliente}/{fecha} en el saludo de un nodo Agente IA por
    los datos reales de la cita agendada (ver editor de flujo, panel del
    nodo). Antes esto solo existía en el mensaje de apertura de la
    campaña, con datos aparte que había que cargar por CSV (ver
    dialer.py); ahora sale directo de la cita ya sincronizada en la
    Agenda, así que funciona igual venga la llamada de una campaña o de
    cualquier otro lado."""
    if not cita:
        return texto
    cuando = f"{fecha_en_palabras(cita.appointment_date.date())} a las {hora_en_palabras(cita.appointment_date)}"
    return texto.replace("{cliente}", cita.patient_name).replace("{fecha}", cuando)


def _trocear(reply_text: str) -> list[str]:
    """Parte la respuesta en frases, y si la primera es larga la corta
    además por coma para que el bot arranque antes.

    Solo se subdivide la primera: las demás se sintetizan mientras suena
    la anterior, y trocearlas de más sería meter pausas sin ganar nada."""
    frases = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", reply_text.strip()) if s.strip()]
    if not frases or len(frases[0]) <= _MAX_PRIMER_TROZO:
        return frases

    primera = frases[0]
    corte = primera.rfind(",", 0, _MAX_PRIMER_TROZO)
    # Sin coma útil no se parte: cortar a mitad de una idea suena peor que
    # esperar un poco más.
    if corte < 20:
        return frases
    return [primera[: corte + 1].strip(), primera[corte + 1 :].strip(), *frases[1:]]


async def _decir_respuesta(
    session: ESLOutboundSession,
    decir,
    reply_text: str,
    bridge: CallBridge,
    turn_key: str,
    allow_bargein: bool = True,
    thinking: "ThinkingSound | None" = None,
) -> bool:
    """Trocea la respuesta por frase y las va reproduciendo en cadena,
    sintetizando la siguiente mientras suena la actual (baja el tiempo hasta
    el primer sonido vs. sintetizar todo el texto de una sola vez). Corta
    apenas hay barge-in. Devuelve True si el paciente interrumpió.

    allow_bargein=False para la despedida final (should_end): no tiene
    sentido dejar que un ruido de fondo la corte a mitad de frase si de
    todos modos la llamada termina ahí — se vivió en una llamada real
    ("se cortó justo al confirmar fecha y hora", el bot se autointerrumpió
    diciendo su propia despedida)."""
    sentences = _trocear(reply_text)
    if not sentences:
        return False

    synth_task = asyncio.create_task(decir(sentences[0], f"{turn_key}_s0"))
    for i, _sentence in enumerate(sentences):
        path = await synth_task
        # El tecleo se corta acá y no antes: mientras se sintetizaba esta
        # frase el silencio seguía existiendo, así que el relleno tiene que
        # durar hasta el instante justo previo a que el bot hable.
        if thinking is not None:
            await thinking.stop()
        if i + 1 < len(sentences):
            synth_task = asyncio.create_task(decir(sentences[i + 1], f"{turn_key}_s{i + 1}"))
        if allow_bargein:
            interrupted = await _play_sentence(session, path, bridge)
        else:
            await session.execute("playback", path)
            interrupted = False
        if interrupted:
            if i + 1 < len(sentences):
                synth_task.cancel()
            return True
    return False


async def handle_call(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    session = ESLOutboundSession(reader, writer)
    try:
        await session.connect()
    except Exception:
        logger.exception("No se pudo establecer la sesión ESL outbound")
        writer.close()
        return

    call_id = session.channel_vars.get("unique-id", str(uuid.uuid4()))
    # El número del CLIENTE, que es con el que se busca su cita.
    # En SALIENTE (campaña) el caller ID es el del PBX, no el del paciente:
    # el número real lo fija `esl.originate` en `nspbx_customer`. En
    # ENTRANTE el cliente sí es quien llama, así que vale el ANI.
    # (Antes se leía solo el ANI y acertaba por accidente, porque el
    # originate estaba metiendo el número marcado en el campo de caller ID.)
    caller_phone = (
        session.channel_vars.get("variable_nspbx_customer")
        or session.channel_vars.get("variable_caller_ani")
        or session.channel_vars.get("caller-caller-id-number")
        or "desconocido"
    )
    logger.info("Voizbot IA: nueva llamada %s de %s", call_id, caller_phone)

    # Saludo personalizado de una campaña de confirmación (ver
    # workers/dialer.py) — reemplaza SOLO la primera frase; el resto de la
    # conversación (tools, objetivo) sigue siendo el de la intención normal.
    saludo_campana = session.channel_vars.get("variable_nspbx_greeting")
    if saludo_campana:
        saludo_campana = unquote(saludo_campana)

    # Cita EXACTA que esta llamada de campaña sincronizó en la Agenda (ver
    # CampaignNumber.appointment_id, cargado en workers/dialer.py). Con
    # esto confirmar_cita/cancelar_cita/reagendar_cita actúan sobre ESA
    # cita puntual en vez de adivinar "la próxima confirmada de este
    # teléfono" — que falla de verdad cuando el mismo número tiene más de
    # una cita a la vez (pasa, y ya causó una confusión real).
    appointment_id_fijo: int | None = None
    _raw_appt_id = session.channel_vars.get("variable_nspbx_appointment_id")
    if _raw_appt_id:
        try:
            appointment_id_fijo = int(_raw_appt_id)
        except ValueError:
            pass

    # Qué nodo del flujo visual (ver app/services/flow_engine.py) entrega
    # esta llamada al voizbot — lo fija el dialplan justo antes del
    # `socket`. Sin esto no hay forma de saber qué prompt/herramientas le
    # tocan a esta llamada (ver app/services/ai_node.py).
    bot_id_raw = session.channel_vars.get("variable_nspbx_bot_id")
    node_id = session.channel_vars.get("variable_nspbx_node_id")
    if not bot_id_raw or not node_id:
        logger.error("Voizbot IA: llamada %s sin nspbx_bot_id/nspbx_node_id (dialplan desactualizado)", call_id)
        await session.execute("hangup", "NORMAL_CLEARING")
        return

    async with async_session() as db:
        nodo = await ai_node.cargar(db, int(bot_id_raw), node_id)
    if nodo is None:
        logger.error(
            "Voizbot IA: llamada %s referencia un nodo Agente IA inexistente (bot %s, nodo %s)",
            call_id, bot_id_raw, node_id,
        )
        await session.execute("hangup", "NORMAL_CLEARING")
        return

    async with async_session() as db:
        row = await db.get(SystemSettings, 1)
        eleven_key = (row.elevenlabs_api_key if row else None) or ""
        deepgram_key = (row.deepgram_api_key if row else None) or ""
        llm_base_url = (getattr(row, "ai_llm_base_url", None) if row else None) or "https://api.deepseek.com/v1"
        llm_model = (getattr(row, "ai_llm_model", None) if row else None) or "deepseek-chat"
        llm_key = (getattr(row, "ai_llm_api_key", None) if row else None) or ""
        llm_provider_name = (getattr(row, "ai_llm_provider_name", None) if row else None) or "el modelo de lenguaje"
        voz_proveedor = (row.ai_voice_provider if row else None) or "elevenlabs"
        stt_proveedor = (getattr(row, "ai_stt_provider", None) if row else None) or "elevenlabs"
        voz_id = (row.ai_voice_id if row else None) or VOICE_ID
        limite_ia = (getattr(row, "max_concurrent_ai_calls", None) if row else None) or 20

    # Sin este tope, un pico de llamadas de IA a la vez (una campaña
    # grande, por ejemplo) puede agotar la memoria/CPU del único proceso
    # que las atiende a todas — y si eso pasa, se caen TODAS las
    # conversaciones de IA en curso a la vez, no solo la más nueva. Mejor
    # rechazar limpio la que sobra que arriesgar eso (ver auditoría de
    # llamadas — capacidad para 100 asesores).
    if len(active_bridges) >= limite_ia:
        logger.warning(
            "Voizbot IA: límite de %s conversaciones simultáneas alcanzado, se rechaza la llamada %s",
            limite_ia, call_id,
        )
        await session.execute("hangup", "NORMAL_CLEARING")
        return

    # Cada pieza necesita su propia key, y solo la del proveedor elegido.
    falta = []
    if not llm_key:
        falta.append(llm_provider_name)
    if stt_proveedor == "deepgram" and not deepgram_key:
        falta.append("Deepgram (transcripción)")
    if stt_proveedor == "elevenlabs" and not eleven_key:
        falta.append("ElevenLabs (transcripción)")
    if voz_proveedor == "deepgram" and not deepgram_key:
        falta.append("Deepgram (voz)")
    if voz_proveedor == "elevenlabs" and not eleven_key:
        falta.append("ElevenLabs (voz)")
    if falta:
        logger.error("Voizbot IA: falta configurar en Ajustes: %s", ", ".join(falta))
        await session.execute("hangup", "NORMAL_CLEARING")
        return

    async def decir(texto: str, nombre: str) -> str:
        """Genera el audio de una frase con el proveedor configurado en
        Ajustes. edge-tts es gratis; ElevenLabs suena mejor pero cuesta
        ~15x más por llamada.

        La extensión importa: ElevenLabs se pide en PCM y se envuelve en
        WAV; edge-tts devuelve MP3 (que mod_shout reproduce bien, es el
        mismo audio que ya usan los flujos IVR)."""
        meter.tts(texto)
        if voz_proveedor == "edge":
            audio, ext = await tts.synthesize(texto, voz_id), "mp3"
        elif voz_proveedor == "deepgram":
            audio, ext = await deepgram.synthesize(texto, voz_id, deepgram_key), "wav"
        else:
            audio, ext = await tts_elevenlabs.synthesize(texto, voz_id, eleven_key), "wav"
        local = sessions_dir / f"{nombre}.{ext}"
        local.write_bytes(audio)
        return f"{FS_SIDE_SOUNDS_DIR}/{AI_SESSIONS_DIR}/{local.name}"

    tools_nodo = llm.tools_para(nodo.tools, exits=nodo.exit_options)
    logger.info("Voizbot IA: llamada %s en el nodo '%s' (%s) del bot %s", call_id, nodo.label, node_id, bot_id_raw)

    messages = [{"role": "system", "content": nodo.prompt}]
    sessions_dir = _local_sessions_dir()
    consumer_task: asyncio.Task | None = None
    bridge: CallBridge | None = None
    meter = UsageMeter(call_id, caller_phone, voz_proveedor, stt_proveedor)

    try:
        # Las dos sesiones exponen la misma interfaz (cola `events` +
        # `send_audio`), así que el resto del loop es idéntico con
        # cualquiera de los dos proveedores.
        abrir_stt = (
            deepgram.DeepgramRealtimeSession(deepgram_key, sample_rate=8000, silence_secs=VAD_SILENCE_SECS)
            if stt_proveedor == "deepgram"
            else tts_elevenlabs.ScribeRealtimeSession(eleven_key, sample_rate=8000, silence_secs=VAD_SILENCE_SECS)
        )
        async with abrir_stt as scribe:
            bridge = CallBridge(scribe, meter)
            active_bridges[call_id] = bridge
            consumer_task = asyncio.create_task(_consume_transcripts(bridge))
            thinking = ThinkingSound(session, ambience.ensure_typing_loop())

            await session.execute("answer")

            ws_url = f"{settings.voicebot_ws_base}/{call_id}"
            uid = session.channel_vars.get("unique-id", "")
            await session.api(f"uuid_audio_fork {uid} start {ws_url} mono 8k voizbot")

            # La cita se busca ANTES de saludar, por dos razones: el saludo
            # puede nombrar la fecha real (el menú grabado ya no la dice,
            # porque venía escrita a mano y se vencía), y el modelo arranca
            # sabiéndola, sin gastar un turno consultándola.
            async with async_session() as db:
                cita = await db.get(Appointment, appointment_id_fijo) if appointment_id_fijo else None
                if cita is None:
                    cita = await find_next_appointment(db, caller_phone)

            # El saludo del nodo (si lo escribieron en el editor) es texto
            # fijo, sin la cita interpolada — el saludo que SÍ verifica
            # identidad ("¿hablo con {nombre}?") solo se arma automático
            # cuando no hay uno propio ni de campaña, y en ese caso el
            # modelo recibe además las instrucciones de qué hacer con la
            # respuesta (ver más abajo).
            greeting_generado = not saludo_campana and not nodo.greeting
            if cita:
                cuando = f"{fecha_en_palabras(cita.appointment_date.date())} a las {hora_en_palabras(cita.appointment_date)}"
                if greeting_generado:
                    # El saludo automático (ver más abajo) ya le preguntó
                    # "¿hablo con {nombre}?" — antes de revelar cualquier
                    # detalle de la cita hay que esperar esa confirmación.
                    # Importa sobre todo en SALIENTE (campaña): puede
                    # contestar cualquiera (un familiar, un número
                    # reasignado), y contarle a quien no corresponde que
                    # hay una cita agendada ya es filtrar un dato privado.
                    extra = (
                        f" Tu saludo ya le preguntó '¿hablo con {cita.patient_name}?' — esperá su respuesta "
                        "ANTES de mencionar la cita.\n"
                        "- Si confirma que sí (dice que sí, dice su propio nombre, responde con naturalidad "
                        "como quien reconoce que le hablan a él/ella): recién ahí seguí con el objetivo de "
                        "esta llamada.\n"
                        "- Si dice que NO es esa persona (número equivocado, no la conoce, etc.): discúlpate "
                        "brevemente, NO reveles ningún detalle de la cita (ni fecha, ni motivo, ni que existe "
                        "una), y llamá a terminar_llamada.\n"
                        "- Si pregunta para qué es, o no responde claro: podés decir que es del consultorio "
                        "para confirmarle un turno, sin dar fecha ni más detalle todavía."
                    )
                else:
                    extra = ""
                messages[0]["content"] += (
                    f"\n\nLa persona que llama tiene una cita agendada para el {cuando}"
                    f" a nombre de {cita.patient_name}.{extra}"
                )
            elif nodo.requiere_cita:
                # Este nodo no tiene sentido sin cita (confirmar, mover o
                # cancelar algo que no existe). Se avisa y se corta, en vez
                # de dejar al bot improvisando.
                logger.info("Voizbot IA: %s llegó al nodo '%s' pero no tiene cita", caller_phone, nodo.label)
                await _decir_respuesta(
                    session, decir,
                    "¡Hola! No encuentro ninguna cita agendada a tu nombre. "
                    "Comunícate con nosotros y con mucho gusto te ayudamos. ¡Hasta pronto!",
                    bridge, f"{call_id}_sincita", allow_bargein=False, thinking=thinking,
                )
                meter.outcome = "no_appointment"
                await session.execute("hangup", "NORMAL_CLEARING")
                return

            if saludo_campana:
                greeting = saludo_campana
            elif nodo.greeting:
                # {cliente}/{fecha} salen de la cita real de la Agenda, no
                # de un dato aparte que haya que cargar por CSV en la
                # campaña (eso ya no existe, ver dialer.py) — si el nodo no
                # tiene "Requiere que la persona ya tenga una cita" marcado
                # y no se encontró ninguna, quedan sin reemplazar tal cual
                # se escribieron.
                greeting = _con_variables(nodo.greeting, cita)
            elif cita:
                # Confirma identidad ANTES de nombrar la cita — ver el
                # bloque de arriba, que le explica al modelo qué hacer con
                # cada posible respuesta a esta pregunta.
                greeting = f"¡Hola! ¿Hablo con {cita.patient_name}?"
            else:
                greeting = "¡Hola! ¿En qué te puedo ayudar?"
            await _decir_respuesta(session, decir, greeting, bridge, f"{call_id}_greeting")
            messages.append({"role": "assistant", "content": greeting})

            for turn in range(nodo.max_turns):
                transcript = None
                while transcript is None:
                    raw = await _wait_utterance(bridge, timeout=TURN_TIMEOUT_SECONDS)
                    if raw is None:
                        # Silencio real (no dijo nada) o se cayó el stream de audio.
                        meter.outcome = "no_speech" if turn == 0 else "completed"
                        await session.execute("hangup", "NORMAL_CLEARING")
                        return
                    if raw.strip():
                        transcript = raw.strip()

                meter.turns += 1
                messages.append({"role": "user", "content": transcript})

                # Desde acá y hasta que el bot hable hay un hueco real
                # (modelo + herramientas + síntesis). Se rellena con el
                # tecleo para que no sea un silencio muerto.
                await thinking.start()
                reply_text, should_end, next_node_id = await _llm_turn(
                    llm_base_url, llm_model, llm_key, messages, caller_phone, meter,
                    tools_nodo, appointment_id_fijo, nodo.exit_targets,
                )

                if reply_text:
                    await _decir_respuesta(
                        session, decir, reply_text, bridge, f"{call_id}_reply{turn}",
                        allow_bargein=not should_end, thinking=thinking,
                    )
                await thinking.stop()  # por si no hubo nada que decir

                if should_end:
                    meter.outcome = "completed"
                    if next_node_id:
                        await _saltar_a_nodo(session, bot_id_raw, next_node_id)
                    else:
                        await session.execute("hangup", "NORMAL_CLEARING")
                    break
            else:
                # Se acabaron los turnos sin que el modelo cerrara: la
                # conversación se fue de largo y conviene poder verlo.
                meter.outcome = "max_turns"
                await session.execute("hangup", "NORMAL_CLEARING")

    except (ConnectionError, asyncio.IncompleteReadError):
        logger.info("Voizbot IA: la llamada %s colgó", call_id)
    except Exception:
        meter.outcome = "error"
        logger.exception("Voizbot IA: error en la conversación %s", call_id)
        try:
            await session.execute("hangup", "NORMAL_CLEARING")
        except Exception:
            pass
    finally:
        # En el finally para que quede registro pase lo que pase: también
        # cuentan (y sobre todo cuentan) las llamadas que terminaron mal.
        await meter.save()
        # Con avanzar_flujo un mismo call_id puede abrir una sesión ESL
        # nueva para el nodo siguiente ANTES de que esta termine de
        # cerrar (ver _saltar_a_nodo) — un pop sin más borraría el bridge
        # de ESA sesión nueva en vez del propio. Solo se saca si el bridge
        # registrado sigue siendo el de esta sesión.
        if active_bridges.get(call_id) is bridge:
            active_bridges.pop(call_id, None)
        if consumer_task:
            consumer_task.cancel()
        try:
            writer.close()
        except Exception:
            pass


async def start_server(host: str = "0.0.0.0", port: int = 8085) -> asyncio.AbstractServer:
    server = await asyncio.start_server(handle_call, host, port)
    logger.info("Voizbot IA (ESL outbound) escuchando en %s:%s", host, port)
    return server
