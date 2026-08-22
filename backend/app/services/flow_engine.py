import json
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.config import settings
from app.services import ai_intents
from app.services.dialplan_recording import append_record_actions

# Ruta que ve FreeSWITCH para los audios de bots.
FS_SOUNDS_BOTS = "/usr/share/freeswitch/sounds/bots"
# "¿Aló?" que se reproduce al contestar, antes del saludo con el menú.
SALUDO_INICIAL = Path(settings.fs_sounds_dir) / "bots" / "saludo_inicial.wav"

VALID_DIGITS = set("0123456789*#")


def _migrar_nodos_ai_legacy(nodes: list[dict]) -> list[dict]:
    """Convierte in-place los nodos `transfer` con `extension == "ai_agent"`
    (la selección fija de gestión de antes del editor de nodos IA, ver
    ai_intents.py) al nuevo tipo `ai_agent` con prompt propio. Mismo `id` y
    mismas conexiones entrantes: no hay que retocar los edges ni reabrir el
    bot en el editor para que la llamada real ya use el nodo migrado — se
    aplica cada vez que se lee el flujo (GET /flow y generación de
    dialplan), no solo una vez."""
    for node in nodes:
        data = node.get("data") or {}
        if node.get("type") != "transfer" or data.get("extension") != "ai_agent":
            continue
        t = ai_intents.plantilla(data.get("ai_intent"))
        node["type"] = "ai_agent"
        node["data"] = {
            "label": data.get("label") or t["label"],
            "prompt": t["prompt"],
            "tools": t["tools"],
            "max_turns": t["max_turns"],
            "greeting": t["greeting"],
            "requiere_cita": t["requiere_cita"],
            "exits": [],
        }
    return nodes


def parse_flow(flow_json: str | None) -> dict | None:
    if not flow_json:
        return None
    try:
        data = json.loads(flow_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    nodes = data.get("nodes")
    edges = data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not nodes:
        return None
    return {"nodes": _migrar_nodos_ai_legacy(nodes), "edges": edges}


def legacy_flow_from_bot(bot) -> dict:
    """Convierte el menú simple viejo (bot.config = {"menu": {...}} +
    welcome_message/greeting_audio_path) a nodos/edges del editor visual,
    para que un bot creado antes del editor de flujo se pueda ver y seguir
    editando ahí en vez de aparecer vacío."""
    nodes = [
        {
            "id": "start",
            "type": "menu",
            "position": {"x": 80, "y": 200},
            "data": {
                "label": "Saludo",
                "start": True,
                "audio_path": bot.greeting_audio_path,
                "tts_text": None if bot.greeting_audio_path else bot.welcome_message,
            },
        }
    ]
    edges = []
    menu: dict[str, str] = {}
    if bot.config:
        try:
            data = json.loads(bot.config)
            raw_menu = data.get("menu") if isinstance(data, dict) else None
            if isinstance(raw_menu, dict):
                menu = {str(k).strip(): str(v).strip() for k, v in raw_menu.items()}
        except (ValueError, TypeError):
            pass
    for i, (digit, target) in enumerate(menu.items()):
        node_id = f"legacy_{digit}"
        nodes.append(
            {
                "id": node_id,
                "type": "transfer",
                "position": {"x": 420, "y": 60 + i * 160},
                "data": {"label": f"Opción {digit}", "extension": target},
            }
        )
        edges.append({"id": f"e_start_{digit}", "source": "start", "target": node_id, "sourceHandle": digit})
    return {"nodes": nodes, "edges": edges}


def _escape_regex_digit(digit: str) -> str:
    return "\\" + digit if digit == "*" else digit


def _start_node(flow: dict) -> dict | None:
    for n in flow["nodes"]:
        if n.get("data", {}).get("start"):
            return n
    return flow["nodes"][0] if flow["nodes"] else None


def _node_audio_action(node: dict) -> ET.Element | None:
    data = node.get("data", {})
    audio_path = data.get("audio_path")
    tts_text = data.get("tts_text")
    if audio_path:
        return ET.Element("action", attrib={"application": "playback", "data": audio_path})
    if tts_text:
        return ET.Element("action", attrib={"application": "speak", "data": f"flite|kal|{tts_text}"})
    return None


def build_voicebot_flow_routes(
    section: ET.Element, context: ET.Element, bot, queues: list | None = None, record_all: bool = False
) -> bool:
    """Genera el dialplan a partir de un flujo visual (nodos + conexiones,
    estilo n8n) guardado en bot.flow_json. Devuelve False si el bot no tiene
    un flujo válido (para que el llamador use el generador simple legado).

    Cada nodo tipo "menu" se traduce en DOS contextos FreeSWITCH propios:
    uno que reproduce su audio y lee el dígito, y otro (separado) que
    enruta ese dígito ya capturado hacia el siguiente nodo — la misma
    técnica de `transfer` a un contexto nuevo que usa el resto del sistema,
    necesaria porque FreeSWITCH evalúa las <condition> de una extension al
    momento de enrutar, no en vivo después de `read`.
    """
    flow = parse_flow(bot.flow_json)
    if not flow:
        return False
    nodes_by_id = {str(n["id"]): n for n in flow["nodes"]}
    start = _start_node(flow)
    if not start:
        return False

    # Una llamada de CAMPAÑA (ver workers/dialer.py) llega con la gestión ya
    # decidida ANTES de marcar — `nspbx_appointment_id` viene seteado desde
    # el originate. A quien contesta no tiene sentido pedirle que marque una
    # opción de menú que nunca vio: si el flujo tiene un nodo Agente IA
    # marcado como "entrada de campaña" (data.campaign_entry), se salta el
    # menú entero y se entrega la llamada directo a ESE nodo. Esta
    # extensión va ANTES que la del menú normal a propósito: FreeSWITCH
    # evalúa las <extension> en orden y se queda con la primera que matchea
    # todas sus <condition>. Si ningún nodo está marcado, se omite y la
    # llamada de campaña entra como cualquier otra (por el nodo inicial).
    campana_node = next(
        (n for n in flow["nodes"] if n.get("type") == "ai_agent" and (n.get("data") or {}).get("campaign_entry")),
        None,
    )
    if campana_node is not None:
        directo_ext = ET.SubElement(
            context, "extension", attrib={"name": f"bot_{bot.id}_{bot.name}_campana", "continue": "false"}
        )
        ET.SubElement(directo_ext, "condition", attrib={"field": "destination_number", "expression": f"^bot_{bot.id}$"})
        directo_cond = ET.SubElement(
            directo_ext, "condition", attrib={"field": "${nspbx_appointment_id}", "expression": "."}
        )
        ET.SubElement(directo_cond, "action", attrib={"application": "answer"})
        ET.SubElement(
            directo_cond,
            "action",
            attrib={"application": "transfer", "data": f"go XML bot_{bot.id}_n{campana_node['id']}"},
        )

    entry_ext = ET.SubElement(context, "extension", attrib={"name": f"bot_{bot.id}_{bot.name}", "continue": "false"})
    entry_cond = ET.SubElement(entry_ext, "condition", attrib={"field": "destination_number", "expression": f"^bot_{bot.id}$"})
    ET.SubElement(entry_cond, "action", attrib={"application": "answer"})
    ET.SubElement(entry_cond, "action", attrib={"application": "sleep", "data": "300"})
    # Un "¿Aló?" corto antes del saludo largo, y una pausa para que la
    # persona conteste — como en una llamada humana. Sin esto el menú
    # completo arranca en el instante exacto en que descuelgan: pisa el
    # "aló" del que contesta y las primeras palabras se pierden.
    if SALUDO_INICIAL.exists():
        ET.SubElement(
            entry_cond,
            "action",
            attrib={"application": "playback", "data": f"{FS_SOUNDS_BOTS}/{SALUDO_INICIAL.name}"},
        )
        ET.SubElement(entry_cond, "action", attrib={"application": "sleep", "data": "1800"})
    ET.SubElement(entry_cond, "action", attrib={"application": "transfer", "data": f"go XML bot_{bot.id}_n{start['id']}"})

    for node in flow["nodes"]:
        node_id = str(node["id"])
        node_type = node.get("type", "menu")
        if node_type == "ai_agent":
            _build_ai_agent_context(section, bot.id, node_id)
            continue
        if node_type != "menu":
            # Un nodo "transfer"/"hangup" normalmente solo se resuelve
            # inline como destino de un edge (ver _append_target_actions),
            # pero además queda con su propio contexto direccionable: lo
            # necesita avanzar_flujo (ver ai_agent.py) para poder saltar
            # ahí desde un Agente IA, no solo desde un menú.
            _build_standalone_context(section, bot.id, node_id, node, queues, record_all)
            continue

        outgoing = [e for e in flow["edges"] if str(e.get("source")) == node_id]
        var_name = f"flow_{bot.id}_{node_id}"
        route_context_name = f"bot_{bot.id}_n{node_id}_route"

        enter_context = ET.SubElement(section, "context", attrib={"name": f"bot_{bot.id}_n{node_id}"})
        enter_ext = ET.SubElement(enter_context, "extension", attrib={"name": "enter", "continue": "false"})
        enter_cond = ET.SubElement(enter_ext, "condition", attrib={"field": "destination_number", "expression": ".*"})

        if not outgoing:
            audio_action = _node_audio_action(node)
            if audio_action is not None:
                enter_cond.append(audio_action)
            ET.SubElement(enter_cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
            continue

        # Nota: se probó pasar el audio directo como prompt de `read` (para
        # evitar perder el dígito en la transición playback→read), pero
        # `read` no reproduce bien un mp3 largo como prompt (aborta en ~1s)
        # y cae al resguardo en inglés — peor que el problema original. Se
        # vuelve a reproducir por separado; sin terminadores en `read`
        # (ver abajo), que sí era una causa real y confirmada de pérdida
        # del dígito.
        audio_action = _node_audio_action(node)
        if audio_action is not None:
            enter_cond.append(audio_action)

        ET.SubElement(enter_cond, "action", attrib={"application": "set", "data": f"{var_name}=x"})
        # `read` demostró (con llamadas reales, 4 pruebas seguidas) no
        # guardar el dígito en la variable aunque el DTMF sí llega —
        # confirmado con un log de diagnóstico justo después. Se reemplaza
        # por `play_and_get_digits`, la aplicación recomendada de
        # FreeSWITCH para menús IVR de un dígito, más robusta que `read`.
        # tries=1 para que la propia app no reintente (nuestro contexto de
        # ruteo ya maneja la opción inválida).
        # Terminador "none" y no "#": con "#" como terminador, y con la
        # expresión anterior (\d|\*) que además no lo aceptaba, una opción
        # configurada en la tecla # era INALCANZABLE — el editor la ofrece
        # (ver VALID_DIGITS) pero el llamante caía siempre en "opción
        # inválida". Como se recoge un solo dígito, no hace falta ningún
        # terminador.
        ET.SubElement(
            enter_cond,
            "action",
            attrib={
                "application": "play_and_get_digits",
                "data": f"1 1 1 7000 none silence_stream://200 silence_stream://200 {var_name} [0-9*#] 5000",
            },
        )
        # El prefijo "opt" NO es decorativo: si nadie marca,
        # play_and_get_digits deja la variable VACÍA (borra incluso el
        # valor puesto con `set` más arriba), y `transfer  XML contexto`
        # con el primer argumento vacío hace que FreeSWITCH corra los
        # argumentos, tome "XML" como destino y muera con
        # NO_ROUTE_DESTINATION. Pasó en una llamada real: la persona no
        # alcanzó a marcar y se le cortó. Con el prefijo el destino nunca
        # es vacío y el caso cae en la extensión de opción inválida.
        ET.SubElement(enter_cond, "action", attrib={"application": "transfer", "data": f"opt${{{var_name}}} XML {route_context_name}"})

        route_context = ET.SubElement(section, "context", attrib={"name": route_context_name})
        for edge in outgoing:
            digit = str(edge.get("sourceHandle", "")).strip()
            if digit not in VALID_DIGITS:
                continue
            target = nodes_by_id.get(str(edge.get("target")))
            if not target:
                continue
            option_ext = ET.SubElement(route_context, "extension", attrib={"name": f"opcion_{digit}", "continue": "false"})
            option_cond = ET.SubElement(option_ext, "condition", attrib={"field": "destination_number", "expression": f"^opt{_escape_regex_digit(digit)}$"})
            _append_target_actions(option_cond, target, bot.id, queues, record_all)

        # Sin marcar nada el destino llega como "opt" pelado; se le da una
        # vuelta más al menú antes de rendirse, que es lo que haría una
        # persona. Solo una: si tampoco marca ahí, cae en la extensión de
        # abajo y se despide.
        reintento_ext = ET.SubElement(route_context, "extension", attrib={"name": "sin_respuesta", "continue": "false"})
        ET.SubElement(reintento_ext, "condition", attrib={"field": "destination_number", "expression": "^opt$"})
        # Segunda condición: que no se haya reintentado ya. Las condiciones
        # de una extension se evalúan en AND, y al fallar una se pasa a la
        # extension siguiente — que es la de "opción inválida". Sin este
        # tope, volver al menú sería un bucle infinito para quien no marca.
        reintento_cond = ET.SubElement(
            reintento_ext, "condition", attrib={"field": f"${{{var_name}_reintento}}", "expression": "^$"}
        )
        ET.SubElement(reintento_cond, "action", attrib={"application": "set", "data": f"{var_name}_reintento=1"})
        ET.SubElement(reintento_cond, "action", attrib={"application": "transfer", "data": f"go XML bot_{bot.id}_n{node_id}"})

        fallback_ext = ET.SubElement(route_context, "extension", attrib={"name": "opcion_invalida", "continue": "false"})
        fallback_cond = ET.SubElement(fallback_ext, "condition", attrib={"field": "destination_number", "expression": ".*"})
        ET.SubElement(fallback_cond, "action", attrib={"application": "speak", "data": "flite|kal|Opcion invalida. Hasta luego."})
        ET.SubElement(fallback_cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})

    return True


def _build_ai_agent_context(section: ET.Element, bot_id: int, node_id: str) -> None:
    """Contexto de un nodo Agente IA: siempre se llega ya con la llamada
    contestada (por entry_ext, por el `transfer` de campaña, o por el
    `transfer` de un nodo menú) — nunca hace su propio `answer`. Fija qué
    nodo del flujo es (nspbx_bot_id + nspbx_node_id) y entrega el control
    al voizbot; `ai_agent.py` carga el prompt, las herramientas y las
    salidas de ESE nodo directo de bot.flow_json (ver ai_agent.py)."""
    enter_context = ET.SubElement(section, "context", attrib={"name": f"bot_{bot_id}_n{node_id}"})
    enter_ext = ET.SubElement(enter_context, "extension", attrib={"name": "enter", "continue": "false"})
    enter_cond = ET.SubElement(enter_ext, "condition", attrib={"field": "destination_number", "expression": ".*"})
    ET.SubElement(enter_cond, "action", attrib={"application": "set", "data": f"nspbx_bot_id={bot_id}"})
    ET.SubElement(enter_cond, "action", attrib={"application": "set", "data": f"nspbx_node_id={node_id}"})
    ET.SubElement(
        enter_cond, "action", attrib={"application": "socket", "data": f"{settings.voicebot_esl_socket} async full"}
    )
    ET.SubElement(enter_cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})


def _build_standalone_context(
    section: ET.Element,
    bot_id: int,
    node_id: str,
    node: dict,
    queues: list | None = None,
    record_all: bool = False,
) -> None:
    """Contexto direccionable para un nodo "transfer"/"hangup" que no es
    destino de ningún menú — sin esto FreeSWITCH no tiene a dónde ir con
    `transfer go XML bot_{id}_n{node_id}` cuando `avanzar_flujo` (ver
    ai_agent.py) salta ahí desde un Agente IA. Reusa exactamente la misma
    lógica que ya resuelve estos nodos como destino de un edge."""
    enter_context = ET.SubElement(section, "context", attrib={"name": f"bot_{bot_id}_n{node_id}"})
    enter_ext = ET.SubElement(enter_context, "extension", attrib={"name": "enter", "continue": "false"})
    enter_cond = ET.SubElement(enter_ext, "condition", attrib={"field": "destination_number", "expression": ".*"})
    _append_target_actions(enter_cond, node, bot_id, queues, record_all)


def _append_target_actions(
    cond: ET.Element, target: dict, bot_id: int, queues: list | None = None, record_all: bool = False
) -> None:
    data = target.get("data", {})
    ttype = target.get("type", "menu")

    if ttype in ("menu", "ai_agent"):
        # Ambos se referencian siempre por su propio contexto — un nodo
        # Agente IA nunca embebe el prompt acá, es ahí donde se fija
        # nspbx_node_id y se entrega el control al voizbot (ver el bucle
        # de arriba y ai_agent.py).
        ET.SubElement(cond, "action", attrib={"application": "transfer", "data": f"go XML bot_{bot_id}_n{target['id']}"})
        return

    if ttype == "hangup":
        audio_action = _node_audio_action(target)
        if audio_action is not None:
            cond.append(audio_action)
        ET.SubElement(cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
        return

    if ttype == "transfer" and str(data.get("target_type") or "extension") == "queue":
        # A una COLA de mod_callcenter y no a una extensión — se busca por
        # id en vez de dialar su DID (Queue.extension) y volver a caer en
        # el context "default": así no depende de que ese número no
        # choque con el de una extensión real (ver auditoría del flujo,
        # esa colisión SÍ puede pasar y dejaría la cola inalcanzable).
        # Mismo mecanismo que usa la entrada directa por DID (ver
        # _append_queue_routes en config_generator.py).
        queue = next((q for q in (queues or []) if q.id == data.get("queue_id")), None)
        if not queue or not queue.enabled:
            ET.SubElement(cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
            return
        ET.SubElement(cond, "action", attrib={"application": "answer"})
        if queue.record and not record_all:
            append_record_actions(cond)
        ET.SubElement(cond, "action", attrib={"application": "set", "data": "hangup_after_bridge=false"})
        ET.SubElement(cond, "action", attrib={"application": "callcenter", "data": f"{queue.name}@$${{domain}}"})
        if queue.failover_extension:
            ET.SubElement(cond, "action", attrib={"application": "transfer", "data": f"{queue.failover_extension} XML default"})
        else:
            ET.SubElement(cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
        return

    if ttype == "transfer":
        extension = str(data.get("extension", "")).strip()
        if not extension:
            ET.SubElement(cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
            return
        whisper_audio = data.get("whisper_audio_path")
        whisper_text = data.get("whisper_text")
        if whisper_audio:
            ET.SubElement(cond, "action", attrib={"application": "set", "data": "bridge_pre_execute_bleg_app=playback"})
            ET.SubElement(cond, "action", attrib={"application": "set", "data": f"bridge_pre_execute_bleg_data={whisper_audio}"})
        elif whisper_text:
            ET.SubElement(cond, "action", attrib={"application": "set", "data": "bridge_pre_execute_bleg_app=speak"})
            ET.SubElement(cond, "action", attrib={"application": "set", "data": f"bridge_pre_execute_bleg_data=flite|kal|{whisper_text}"})
        ET.SubElement(cond, "action", attrib={"application": "set", "data": "hangup_after_bridge=true"})
        # $${domain} (variable GLOBAL de FreeSWITCH, siempre existe) en vez
        # de ${domain_name} (variable POR LLAMADA que solo queda seteada si
        # se entró por una ruta entrante que la define explícitamente) —
        # con ${domain_name} la transferencia fallaba en silencio (bridge a
        # "user/1010@" con dominio vacío) al marcar el bot directo desde una
        # extensión o desde una campaña, en vez de por una llamada entrante real.
        ET.SubElement(cond, "action", attrib={"application": "bridge", "data": f"user/{extension}@$${{domain}}"})
        return

    ET.SubElement(cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
