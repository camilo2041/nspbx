"""Chat de diagnóstico: un admin pregunta en lenguaje natural por fallas
del sistema y el modelo responde SOLO a partir de herramientas que
consultan datos reales (CDR, resultado de llamadas del voizbot IA, estado
de troncales/ESL, disco, backups, errores del backend) — mismo patrón de
tool-calling que ya usa el voizbot conversacional (ver
app/services/ai_agent.py), aplicado acá a diagnóstico en vez de agenda.

Reusa `llm.chat`/`llm.parse_tool_calls` (genéricos, sin acoplarse a
`llm.TOOLS`, que es del voizbot) y, para no duplicar lógica, llama
DIRECTO a las funciones de los endpoints de system.py: son funciones
Python normales — `Depends(...)` es solo un valor por defecto que no
molesta si el argumento se pasa explícito, así que no hace falta tocar
esos archivos ni exponerlos de otra forma.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.api.calls import _acotar, _solo_suyas
from app.api.system import diagnostics as _diagnostics
from app.api.system import maintenance_status as _maintenance_status
from app.api.system import recursos as _recursos
from app.core.database import async_session
from app.models import AiCallUsage, CallLog, SystemErrorLog, SystemSettings, User
from app.services import llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sos el asistente de diagnóstico del panel NSPBX (una \
central telefónica). Quien te escribe es un administrador del sistema, \
no un paciente ni un cliente — hablále técnico y directo, sin rodeos ni \
frases de atención al cliente.

REGLA DURA: nunca afirmes una causa o un estado sin haber consultado la \
herramienta correspondiente en ESTE turno. Si las herramientas no traen \
suficiente para explicar algo, decilo con todas las letras ("con los \
datos que tengo no puedo saber por qué pasó eso") en vez de inventar una \
causa plausible.

Cuando encuentres algo mal, sé concreto: qué está mal, desde cuándo (si \
los datos lo dicen), y si hay una acción obvia sugerila (ej. "la troncal \
X está anunciando una IP privada, revisá su configuración de red/NAT").

Además de diagnosticar, orientás sobre DÓNDE se hace cada cosa en el \
panel: si preguntan "dónde hago X", "cómo configuro Y" o "para qué \
sirve Z", usá SIEMPRE la herramienta mapa_sistema (que describe cada \
pantalla y ejemplos) antes de responder, y respondé con la ruta concreta \
(ej. "La música de espera se cambia en Ajustes → Música de espera").

Las respuestas son para leer en una pantalla de chat: párrafos cortos, \
sin firmas ni despedidas. Si la pregunta no tiene que ver con el \
funcionamiento del sistema, decí que solo podés ayudar con diagnóstico \
y orientación del propio NSPBX."""


MAPA_SISTEMA = """Mapa del panel NSPBX (qué hace cada pantalla y dónde se hace cada tarea):

- Inicio / Dashboard (/): resumen general de la central.
- Call Center (/call-center): gráficas y métricas de llamadas, citas y uso IA.
- Softphone (/softphone): el teléfono del navegador — llamar, contestar, silenciar, poner en espera (con música), no molestar.
- Llamadas (/calls): historial (CDR), escuchar/descargar grabaciones, resúmenes, y supervisión en vivo (espiar/susurrar/unirse) con filtros por cola/voizbot/extensión.
- Citas (/appointments): agenda del consultorio y gestiones (confirmar, cancelar, reagendar).
- Extensiones (/extensions): crear/editar extensiones SIP (número, contraseña, buzón de voz, nombre) y probar una llamada.
- Troncales (/trunks): proveedores SIP de salida — servidor, usuario/password, registro, caller ID, transporte.
- Rutas entrantes (/inbound-routes): qué pasa con cada número entrante (DID) — derivar a extensión, cola, voizbot o condición de tiempo.
- Rutas salientes (/outbound-routes): qué troncal se usa según el patrón del número marcado (con strip/prepend de dígitos).
- Condiciones de tiempo (/time-conditions): horarios hábiles/fuera de horario (se enlazan desde Rutas entrantes).
- Lista negra (/blacklist): números rechazados automáticamente al entrar.
- Prioritarias (VIP) (/priority-numbers): números que se marcan como prioritarios (etiqueta PRIORITARIO + anuncio en colas).
- Colas (/queues): colas de atención — agentes, estrategia, anuncio de entrada, desbordamiento.
- Voizbots (/voicebots): IVR de teclas y agentes conversacionales con IA (editor de flujo visual por nodos).
- Campañas (/campaigns): marcación masiva (autodialer) con números y mensaje.
- Usuarios (/users): cuentas del panel y sus permisos/rol.
- Consumo IA (/ai-usage): uso y costo estimado de las llamadas del voizbot.
- Logs (/logs): consola de logs de FreeSWITCH en vivo.
- Ajustes (/settings): toda la configuración, en pestañas:
  - Diagnóstico: estado real de FreeSWITCH, softphone, IP pública y troncales.
  - Central: nombre/dominio, conexión FreeSWITCH (ESL) y softphones.
  - Voizbot IA: modelo de lenguaje, voz/transcripción, agente externo y tarifas.
  - Capacidad y disco: límites de llamadas/concurrencia y espacio de grabaciones/respaldos.
  - Música de espera: qué pistas suenan en hold.
- Asistente (/assistant): este mismo chat a pantalla completa.

Ejemplos de "dónde hago X":
- Crear una extensión → Extensiones.
- Agregar un proveedor de llamadas → Troncales.
- Crear una cola de atención → Colas.
- Crear un menú IVR o un agente con IA → Voizbots.
- Cambiar la música de espera → Ajustes → Música de espera.
- Ver por qué no entraron llamadas → Llamadas o Ajustes → Diagnóstico.
- Lanzar una campaña de llamadas → Campañas.
- Bloquear un número → Lista negra.
- Marcar un número como prioritario → Prioritarias (VIP).
- Desviar las llamadas de mi extensión → marcar *72<número> (o *21) para activar, *73 para apagar.
- Entrar a una conferencia → marcar *64<número-de-sala> (se crea sola).
- Grabar una llamada en curso → botón "Grabar" en el softphone.
- Escuchar mensajes de buzón → en el softphone, sección "Buzón de voz" (o *97 desde el teléfono)."""


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "—"


async def _llamadas_fallidas(session, usuario: User, args: dict) -> str:
    dias = int(args.get("dias") or 3)
    limite = min(int(args.get("limite") or 15), 50)
    desde = datetime.utcnow() - timedelta(days=dias)
    query = _acotar(select(CallLog), _solo_suyas(usuario)).where(
        CallLog.status != "answered", CallLog.started_at >= desde
    ).order_by(CallLog.started_at.desc()).limit(limite)
    filas = (await session.execute(query)).scalars().all()
    if not filas:
        return f"No hay llamadas fallidas registradas en los últimos {dias} días."
    lineas = [
        f"- {_fmt(c.started_at)} | {c.direction} | de {c.caller_number or '—'} a {c.callee_number or '—'} "
        f"| estado: {c.status} | causa: {c.hangup_cause or '—'}"
        for c in filas
    ]
    return f"Llamadas fallidas en los últimos {dias} días (hasta {limite}):\n" + "\n".join(lineas)


async def _estadisticas_llamadas(session, usuario: User, args: dict) -> str:
    dias = int(args.get("dias") or 7)
    desde = datetime.utcnow() - timedelta(days=dias)
    propia = _solo_suyas(usuario)
    result = await session.execute(
        _acotar(select(CallLog.status, func.count(CallLog.id)), propia)
        .where(CallLog.started_at >= desde)
        .group_by(CallLog.status)
    )
    counts = dict(result.all())
    total_min = (
        await session.execute(
            _acotar(select(func.coalesce(func.sum(CallLog.billsec), 0)), propia).where(CallLog.started_at >= desde)
        )
    ).scalar() or 0
    total = sum(counts.values())
    fallidas = counts.get("failed", 0) + counts.get("rejected", 0) + counts.get("cancelled", 0)
    return (
        f"Últimos {dias} días: {total} llamadas en total — "
        f"{counts.get('answered', 0)} contestadas, {counts.get('no_answer', 0)} sin respuesta, "
        f"{counts.get('busy', 0)} ocupado, {fallidas} fallidas. "
        f"{round(total_min / 60, 1)} minutos hablados en total."
    )


async def _llamadas_ia_fallidas(session, args: dict) -> str:
    dias = int(args.get("dias") or 3)
    limite = min(int(args.get("limite") or 15), 50)
    desde = datetime.utcnow() - timedelta(days=dias)
    query = (
        select(AiCallUsage)
        .where(AiCallUsage.started_at >= desde, AiCallUsage.outcome != "completed")
        .order_by(AiCallUsage.started_at.desc())
        .limit(limite)
    )
    filas = (await session.execute(query)).scalars().all()
    if not filas:
        return f"No hay llamadas del voizbot IA con resultado fallido en los últimos {dias} días."
    lineas = [
        f"- {_fmt(f.started_at)} | {f.phone or '—'} | resultado: {f.outcome} | {f.turns} turnos | "
        f"{f.duration_seconds}s"
        for f in filas
    ]
    return f"Llamadas del voizbot IA no resueltas en los últimos {dias} días (hasta {limite}):\n" + "\n".join(lineas)


async def _estado_sistema(session, args: dict) -> str:
    d = await _diagnostics(session=session)
    lineas = [
        f"ESL (FreeSWITCH): {'OK' if d['esl_ok'] else 'NO RESPONDE'}",
        f"WebSocket del softphone: {'OK' if d['sip_ws_ok'] else 'NO RESPONDE'}",
        f"IP pública del servidor: {d['public_ip'] or 'desconocida'}",
    ]
    for t in d["trunks"]:
        alerta = " ⚠ IP de contacto no alcanzable desde internet" if t["contact_no_alcanzable"] else ""
        lineas.append(
            f"- Troncal '{t['name']}' ({t['gateway_host']}): estado={t['state'] or '—'}, "
            f"registro={t['status'] or '—'}, contacto={t['contact_ip'] or '—'}{alerta}"
        )
    return "\n".join(lineas)


async def _salud_recursos(args: dict) -> str:
    r = await _recursos()
    lineas = [
        f"CPU: {r['cpu']['porcentaje']}% ({r['cpu']['nucleos']} núcleos)",
        f"Memoria: {r['memoria']['usado_gb']}/{r['memoria']['total_gb']} GB ({r['memoria']['porcentaje']}%)",
        f"Swap: {r['swap']['usado_gb']}/{r['swap']['total_gb']} GB ({r['swap']['porcentaje']}%)",
    ]
    for d in r["discos"]:
        lineas.append(f"Disco '{d['nombre']}' ({d['punto']}): {d['usado_gb']}/{d['total_gb']} GB ({d['porcentaje']}%)")
    return "\n".join(lineas)


async def _estado_backups(session, args: dict) -> str:
    m = await _maintenance_status(session=session)
    return (
        f"Backups: {'habilitados' if m['backup_enabled'] else 'DESHABILITADOS'}, "
        f"último: {_fmt(m['last_backup_at'])} ({'OK' if m['last_backup_ok'] else 'FALLÓ: ' + str(m['last_backup_error'])}), "
        f"{m['backups_count']} guardados ({m['backups_size_mb']} MB), retención {m['backup_retention_days']} días.\n"
        f"Grabaciones: {m['recordings_count']} archivos ({m['recordings_size_gb']} GB de un tope de "
        f"{m['recordings_max_gb']} GB), retención {m['recordings_retention_days']} días."
    )


async def _errores_backend(session, args: dict) -> str:
    dias = int(args.get("dias") or 3)
    limite = min(int(args.get("limite") or 15), 50)
    desde = datetime.utcnow() - timedelta(days=dias)
    query = (
        select(SystemErrorLog)
        .where(SystemErrorLog.created_at >= desde)
        .order_by(SystemErrorLog.created_at.desc())
        .limit(limite)
    )
    filas = (await session.execute(query)).scalars().all()
    if not filas:
        return f"No hay errores registrados del backend en los últimos {dias} días."
    lineas = [f"- {_fmt(e.created_at)} | {e.logger_name}: {e.message}" for e in filas]
    return f"Errores del backend en los últimos {dias} días (hasta {limite}):\n" + "\n".join(lineas)


async def _mapa_sistema(session, args: dict) -> str:
    return MAPA_SISTEMA


_DIAS_LIMITE_PARAMS = {
    "type": "object",
    "properties": {
        "dias": {"type": "integer", "description": "Cuántos días atrás mirar. Por defecto 3."},
        "limite": {"type": "integer", "description": "Máximo de filas a devolver. Por defecto 15."},
    },
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "llamadas_fallidas",
            "description": "Lista llamadas telefónicas (CDR) que NO se contestaron: sin respuesta, ocupado, rechazadas o canceladas, con la causa que reportó FreeSWITCH.",
            "parameters": _DIAS_LIMITE_PARAMS,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estadisticas_llamadas",
            "description": "Totales de llamadas de los últimos N días: contestadas, sin respuesta, ocupado, fallidas y minutos hablados.",
            "parameters": {
                "type": "object",
                "properties": {"dias": {"type": "integer", "description": "Por defecto 7."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "llamadas_ia_fallidas",
            "description": "Lista llamadas del voizbot conversacional con IA que NO terminaron resueltas (colgó sin hablar, se le acabaron los turnos, o hubo un error interno).",
            "parameters": _DIAS_LIMITE_PARAMS,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estado_sistema",
            "description": "Estado en vivo de FreeSWITCH (ESL), el WebSocket del softphone, la IP pública, y de cada troncal SIP (registrada, y si su IP de contacto es alcanzable desde internet).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "salud_recursos",
            "description": "Uso de CPU, memoria, swap y disco del servidor que hospeda todo el sistema.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estado_backups",
            "description": "Si los backups automáticos de la base de datos están al día, y cuánto espacio ocupan backups y grabaciones frente a sus topes configurados.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "errores_backend",
            "description": "Errores internos (excepciones) del propio backend en los últimos N días — para diagnosticar fallas que no son de una llamada puntual sino del sistema en sí.",
            "parameters": _DIAS_LIMITE_PARAMS,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mapa_sistema",
            "description": "Mapa del panel: qué hace cada pantalla y dónde se hace cada tarea (crear extensiones/troncales/colas/voizbots, música de espera, ver llamadas, etc.). Usar SIEMPRE que pregunten 'dónde hago X', 'cómo configuro Y' o 'para qué sirve Z'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


async def _ejecutar_tool(session, usuario: User, name: str, args: dict) -> str:
    try:
        if name == "llamadas_fallidas":
            return await _llamadas_fallidas(session, usuario, args)
        if name == "estadisticas_llamadas":
            return await _estadisticas_llamadas(session, usuario, args)
        if name == "llamadas_ia_fallidas":
            return await _llamadas_ia_fallidas(session, args)
        if name == "estado_sistema":
            return await _estado_sistema(session, args)
        if name == "salud_recursos":
            return await _salud_recursos(args)
        if name == "estado_backups":
            return await _estado_backups(session, args)
        if name == "errores_backend":
            return await _errores_backend(session, args)
        if name == "mapa_sistema":
            return await _mapa_sistema(session, args)
    except Exception as exc:
        logger.exception("Chat de diagnóstico: falló la herramienta %s", name)
        return f"La herramienta {name} falló al ejecutarse: {exc}"
    return "Herramienta desconocida."


async def responder(messages: list[dict], usuario: User) -> str:
    """Un turno completo: le pasa la conversación al modelo, ejecuta las
    tool calls que pida contra datos reales, y devuelve el texto final.
    Mismo bucle que `ai_agent._llm_turn`, sin turnos de voz."""
    async with async_session() as db:
        row = await db.get(SystemSettings, 1)
        base_url = (getattr(row, "ai_llm_base_url", None) if row else None) or "https://api.deepseek.com/v1"
        model = (getattr(row, "ai_llm_model", None) if row else None) or "deepseek-chat"
        api_key = (getattr(row, "ai_llm_api_key", None) if row else None) or ""

    if not api_key:
        raise ValueError("Falta configurar la API key del modelo de lenguaje en Ajustes")

    for _ in range(5):  # tope de vueltas tool-call -> tool-call por turno
        message, _uso = await llm.chat(base_url, model, api_key, messages, tools=TOOLS)
        messages.append(message)
        calls = llm.parse_tool_calls(message)
        if not calls:
            return message.get("content") or "No tengo una respuesta para eso."
        async with async_session() as session:
            for call_id, name, args in calls:
                resultado = await _ejecutar_tool(session, usuario, name, args)
                messages.append({"role": "tool", "tool_call_id": call_id, "content": resultado})

    return "Se me complicó reunir toda la información para responder eso. ¿Podés preguntar algo más puntual?"
