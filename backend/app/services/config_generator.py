import json
import xml.etree.ElementTree as ET

from app.core.runtime_settings import runtime_settings
from app.services import voice_prompts
from app.services.dialplan_recording import append_record_actions
from app.services.flow_engine import build_voicebot_flow_routes


def _e(tag: str, text: str | None = None, attrib: dict | None = None) -> ET.Element:
    el = ET.Element(tag, attrib or {})
    if text:
        el.text = text
    return el


def _dashed_phone(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def build_directory_xml(extensions: list) -> str:
    """Genera la seccion <section name='directory'> con las extensiones."""
    root = _e("document", attrib={"type": "freeswitch/xml"})
    section = ET.SubElement(root, "section", attrib={"name": "directory"})
    domain = ET.SubElement(
        section, "domain", attrib={"name": runtime_settings.fs_domain}
    )
    params = ET.SubElement(domain, "params")
    ET.SubElement(params, "param", attrib={"name": "dial-string", "value": "{^^:sip_invite_domain=${dialed_domain}:presence_id=${dialed_user}@${dialed_domain}}${sofia_contact(*/${dialed_user}@${dialed_domain})}"})
    groups = ET.SubElement(domain, "groups")
    group = ET.SubElement(groups, "group", attrib={"name": "default"})
    users = ET.SubElement(group, "users")
    for ext in extensions:
        user = ET.SubElement(users, "user", attrib={"id": ext.number})
        params = ET.SubElement(user, "params")
        ET.SubElement(params, "param", attrib={"name": "password", "value": ext.password})
        ET.SubElement(params, "param", attrib={"name": "vm-password", "value": ext.password})
        v = ET.SubElement(user, "variables")
        if ext.caller_id_name:
            ET.SubElement(v, "variable", attrib={"name": "user_context", "value": "default"})
            ET.SubElement(v, "variable", attrib={"name": "effective_caller_id_name", "value": ext.caller_id_name})
        ET.SubElement(v, "variable", attrib={"name": "effective_caller_id_number", "value": ext.number})
        ET.SubElement(v, "variable", attrib={"name": "user_context", "value": "default"})
    return ET.tostring(root, encoding="unicode")


def _decir(condition: ET.Element, prompt_key: str, texto_respaldo: str) -> None:
    """Reproduce un aviso corto pre-generado (voz real, en español) si ya
    existe; si todavía no se sintetizó (recién instalado, sin API key de
    Deepgram cargada), cae a `speak` con flite como único respaldo posible
    — suena peor, pero ninguna llamada se queda sin ningún aviso."""
    ruta = voice_prompts.prompt_path(prompt_key)
    if ruta:
        ET.SubElement(condition, "action", attrib={"application": "playback", "data": ruta})
    else:
        ET.SubElement(condition, "action", attrib={"application": "speak", "data": f"flite|kal|{texto_respaldo}"})


def _append_dnd_feature_codes(context: ET.Element) -> None:
    """*78 activa "no molestar" para quien marca, *79 lo apaga.

    Es el código de función estándar que cualquier softphone o teléfono
    SIP de escritorio sabe marcar (muchos hasta lo mandan solos cuando se
    aprieta su propio botón de DND) — no depende de que el cliente tenga
    nada especial, solo de que el servidor sepa qué hacer con esos dígitos.

    El estado se guarda en la base interna de FreeSWITCH (`db insert`),
    no en Postgres: se consulta en caliente en CADA llamada entrante a una
    extensión (ver _append_dnd_hook) y no vale la pena el viaje a la base
    de la app por algo que se prende y apaga desde el propio teléfono.
    """
    activar = ET.SubElement(context, "extension", attrib={"name": "nspbx_dnd_on", "continue": "false"})
    c1 = ET.SubElement(activar, "condition", attrib={"field": "destination_number", "expression": r"^\*78$"})
    ET.SubElement(c1, "action", attrib={"application": "answer"})
    ET.SubElement(c1, "action", attrib={"application": "db", "data": "insert/dnd/${caller_id_number}/on"})
    _decir(c1, "dnd_on", "No molestar activado.")
    ET.SubElement(c1, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})

    desactivar = ET.SubElement(context, "extension", attrib={"name": "nspbx_dnd_off", "continue": "false"})
    c2 = ET.SubElement(desactivar, "condition", attrib={"field": "destination_number", "expression": r"^\*79$"})
    ET.SubElement(c2, "action", attrib={"application": "answer"})
    ET.SubElement(c2, "action", attrib={"application": "db", "data": "delete/dnd/${caller_id_number}/on"})
    _decir(c2, "dnd_off", "No molestar desactivado.")
    ET.SubElement(c2, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})


def _append_dnd_hook(context: ET.Element, extensions: list) -> None:
    """Si la extensión destino tiene DND activo, corta acá con ocupado en
    vez de timbrar. Va ANTES de Local_Extension, con continue="false" —
    solo se llega a cortar si de verdad hay DND activo; si no, esta
    extensión ni siquiera matchea y la llamada sigue de largo.

    La consulta a la base de FreeSWITCH va DIRECTO en el `field` de la
    condición (no en un `set` de una extensión previa): probado en vivo
    que separar "guardar la variable" y "leerla" en dos extensiones
    distintas no funciona de forma confiable — la variable quedaba
    seteada (confirmado con uuid_dump) pero la condición que la leía
    después no la evaluaba. Con la consulta inline en la misma condición
    no hay ese problema.
    """
    if not extensions:
        return
    numbers = "|".join(e.number for e in extensions)

    cortar = ET.SubElement(context, "extension", attrib={"name": "nspbx_dnd_cortar", "continue": "false"})
    c1 = ET.SubElement(cortar, "condition", attrib={"field": "destination_number", "expression": f"^({numbers})$"})
    c2 = ET.SubElement(cortar, "condition", attrib={"field": "${db(select/dnd/${destination_number})}", "expression": "^on$"})
    ET.SubElement(c2, "action", attrib={"application": "answer"})
    _decir(c2, "dnd_no_disponible", "La extensión no está disponible en este momento.")
    ET.SubElement(c2, "action", attrib={"application": "hangup", "data": "USER_BUSY"})


def _append_local_extension_route(context: ET.Element, extensions: list) -> None:
    """Extension a extension (Local_Extension)."""
    if not extensions:
        return
    extension = ET.SubElement(context, "extension", attrib={"name": "Local_Extension", "continue": "false"})
    numbers = "|".join(e.number for e in extensions)
    condition = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": f"^({numbers})$"})
    ET.SubElement(condition, "action", attrib={"application": "log", "data": "Llamada local a extension"})
    # SIN "answer" acá — contestaba la pata de quien LLAMA antes de
    # siquiera intentar timbrarle a quien recibe. Entre dos softphones
    # (SIP.js/WebRTC), eso le manda un 200 OK al que llama al instante:
    # su pantalla salta a "en llamada" sin que el otro lado haya hecho
    # nada, y a quien recibe nunca le suena porque bridge todavía ni
    # arrancó. Sin este "answer", la pata de quien llama se queda
    # timbrando de verdad hasta que el destino conteste — es `bridge`
    # el que se encarga de contestarla en ese momento, no antes.
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "hangup_after_bridge=true"})
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "continue_on_fail=true"})
    # $${domain} (global, siempre existe) en vez de ${domain_name} (variable
    # por llamada que no queda seteada si se llega aquí sin pasar antes por
    # una ruta entrante que la defina explícitamente — ver flow_engine.py).
    ET.SubElement(condition, "action", attrib={"application": "bridge", "data": "user/${destination_number}@$${domain}"})
    anti = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": f"^({numbers})$"})
    anti.set("break", "on-false")
    ET.SubElement(anti, "action", attrib={"application": "hangup", "data": "NO_ANSWER"})


def _parse_bot_menu(config_json: str | None) -> dict[str, str]:
    """Lee `{"menu": {"1": "1000", "2": "1001"}}` del campo config del bot.

    Solo se aceptan teclas de un dígito (0-9, *, #) mapeadas a un número de
    extensión, para mantener el IVR simple (sin IA) y su enrutamiento seguro.
    """
    if not config_json:
        return {}
    try:
        data = json.loads(config_json)
    except (ValueError, TypeError):
        return {}
    menu = data.get("menu") if isinstance(data, dict) else None
    if not isinstance(menu, dict):
        return {}
    out: dict[str, str] = {}
    for digit, target in menu.items():
        digit = str(digit).strip()
        target = str(target).strip()
        if len(digit) == 1 and digit in "0123456789*#" and target:
            out[digit] = target
    return out


def _append_voicebot_routes(
    section: ET.Element, context: ET.Element, bots: list, queues: list | None = None, record_all: bool = False
) -> None:
    """IVR simple (sin IA): saluda con audio o texto (TTS) y enruta según la
    tecla presionada hacia una extensión, reutilizando Local_Extension.

    IMPORTANTE: las condiciones de un <extension> se evalúan TODAS al
    momento de enrutar la llamada (antes de ejecutar ninguna acción), no en
    vivo mientras corre `read`. Por eso el dígito capturado no se puede
    comparar con `<condition field="${var}">` en la MISMA extensión — para
    cuando se evalúa, la variable aún no existe. La forma correcta es
    transferir a un CONTEXTO nuevo usando el valor de la variable como
    destination_number: `transfer` resuelve eso en tiempo de ejecución, y el
    contexto destino hace un dialplan-hunt nuevo con el dígito ya capturado.
    """
    for bot in bots:
        # `bot_type` ("ivr" vs "ai") es hoy solo una etiqueta para la lista
        # de voizbots — no cambia cómo se genera el dialplan. Antes un bot
        # creado como "ai" se saltaba ACÁ ENTERO y quedaba inmarcable (ni
        # siquiera generaba la extensión bot_{id}), de cuando el editor de
        # flujo (con nodos Agente IA, ver flow_engine.py) todavía no
        # existía. Un bot "puramente IA" hoy se arma poniendo el nodo
        # inicial del flujo como Agente IA en vez de un menú — no necesita
        # ningún trato especial acá.
        if build_voicebot_flow_routes(section, context, bot, queues, record_all):
            continue  # el bot tiene un flujo visual (nodos/edges); ya se generó su dialplan
        menu = _parse_bot_menu(bot.config)
        var_name = f"ivr_digit_{bot.id}"
        menu_context_name = f"ivr_menu_{bot.id}"

        extension = ET.SubElement(context, "extension", attrib={"name": f"bot_{bot.id}_{bot.name}", "continue": "false"})
        entry = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": f"^bot_{bot.id}$"})
        ET.SubElement(entry, "action", attrib={"application": "answer"})
        ET.SubElement(entry, "action", attrib={"application": "sleep", "data": "300"})

        if not menu:
            if bot.greeting_audio_path:
                ET.SubElement(entry, "action", attrib={"application": "playback", "data": bot.greeting_audio_path})
            elif bot.welcome_message:
                ET.SubElement(entry, "action", attrib={"application": "speak", "data": f"flite|kal|{bot.welcome_message}"})
            ET.SubElement(entry, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
            continue

        # Nota: se probó pasar el audio directo como prompt de `read` para
        # evitar perder el dígito en la transición playback→read, pero
        # `read` no reproduce bien un mp3 largo como prompt (aborta en ~1s
        # y cae al resguardo en inglés) — peor que el problema original.
        # Se reproduce por separado; sin terminadores en `read` (abajo),
        # que sí era una causa real y confirmada de pérdida del dígito.
        if bot.greeting_audio_path:
            ET.SubElement(entry, "action", attrib={"application": "playback", "data": bot.greeting_audio_path})
        elif bot.welcome_message:
            # mod_flite no trae voz en español (se oye con acento inglés);
            # es solo resguardo si no hay audio propio.
            ET.SubElement(entry, "action", attrib={"application": "speak", "data": f"flite|kal|{bot.welcome_message}"})

        # Valor por defecto ANTES de leer el dígito: si el que llama no
        # marca nada (timeout), la variable queda vacía — eso rompe el
        # parseo de argumentos de `transfer` más abajo (un exten vacío
        # desplaza los argumentos siguientes). "x" nunca matchea ningún
        # dígito real, así que cae limpio en la opción inválida.
        ET.SubElement(entry, "action", attrib={"application": "set", "data": f"{var_name}=x"})
        # `read` demostró (con llamadas reales) no guardar el dígito en la
        # variable aunque el DTMF sí llega — confirmado con un log de
        # diagnóstico. Se usa `play_and_get_digits`, la aplicación
        # recomendada de FreeSWITCH para menús IVR de un dígito.
        ET.SubElement(
            entry,
            "action",
            attrib={
                "application": "play_and_get_digits",
                "data": f"1 1 1 7000 # silence_stream://200 silence_stream://200 {var_name} \\d|\\* 5000",
            },
        )
        # Transferir usando el valor EN VIVO de la variable (se resuelve al
        # ejecutar, no al enrutar) hacia un contexto dedicado a este menú.
        ET.SubElement(entry, "action", attrib={"application": "transfer", "data": f"${{{var_name}}} XML {menu_context_name}"})

        # Contexto aparte: aquí destination_number SÍ es el dígito recién
        # capturado, porque el dialplan-hunt vuelve a ocurrir al transferir.
        menu_context = ET.SubElement(section, "context", attrib={"name": menu_context_name})
        for digit, target in menu.items():
            option = ET.SubElement(menu_context, "extension", attrib={"name": f"opcion_{digit}", "continue": "false"})
            cond = ET.SubElement(option, "condition", attrib={"field": "destination_number", "expression": f"^{_escape_regex_digit(digit)}$"})
            ET.SubElement(cond, "action", attrib={"application": "transfer", "data": f"{target} XML default"})

        fallback_ext = ET.SubElement(menu_context, "extension", attrib={"name": "opcion_invalida", "continue": "false"})
        fallback = ET.SubElement(fallback_ext, "condition", attrib={"field": "destination_number", "expression": ".*"})
        ET.SubElement(fallback, "action", attrib={"application": "answer"})
        # Si el bot tiene audio propio, no se mezcla con voz sintética de
        # respaldo al final — se cuelga en silencio. El TTS de "opción
        # inválida" solo se usa cuando TODO el bot es por voz sintética
        # (sin audio propio subido).
        if not bot.greeting_audio_path:
            ET.SubElement(fallback, "action", attrib={"application": "speak", "data": "flite|kal|Opcion invalida. Hasta luego."})
        ET.SubElement(fallback, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})


def _escape_regex_digit(digit: str) -> str:
    """Escapa el * (cuantificador en regex) al construir la expresión; # no
    necesita escape, es un carácter literal."""
    return "\\" + digit if digit == "*" else digit


def orden_troncales(trunks: list, principal_id: int | None = None) -> list:
    """Troncales habilitadas, en el orden en que hay que intentarlas.

    Si se indica `principal_id` (la troncal que alguien eligió a propósito
    para una campaña o un click-to-call), va primero; el resto entra como
    respaldo en el orden en que se dieron de alta. Sin `principal_id`,
    simplemente el orden de alta decide quién es la principal.

    Esta lista es la base de la redundancia de salida: con una sola
    troncal habilitada, el comportamiento es idéntico a antes (una sola
    pata). En cuanto hay una segunda troncal habilitada, cualquier salida
    empieza a poder recurrir a ella sola, sin que nadie tenga que
    reaccionar a mitad de una llamada real.
    """
    habilitadas = sorted((t for t in trunks if t.enabled), key=lambda t: t.id)
    if principal_id is None:
        return habilitadas
    principal = next((t for t in habilitadas if t.id == principal_id), None)
    if principal is None:
        return habilitadas
    return [principal] + [t for t in habilitadas if t.id != principal_id]


def _append_outbound_route(context: ET.Element, trunks: list) -> None:
    """Ruta de salida: números externos (7-15 dígitos) vía la cadena de
    troncales habilitadas, en serie (separadas por "|" en `bridge`, que es
    la sintaxis de FreeSWITCH para "probá la primera; si no contesta o la
    rechaza, probá la siguiente"). Con una sola troncal habilitada, esto
    genera exactamente la misma llamada de antes.

    Nota: es una ruta única simple (no hay aún "outbound routes" con
    patrones por troncal como en Issabel/FreePBX). Si se necesitan varias
    troncales con distintos patrones de marcado, esto debe evolucionar a
    algo configurable.
    """
    cadena = orden_troncales(trunks)
    if not cadena:
        return
    extension = ET.SubElement(context, "extension", attrib={"name": "Outbound_External", "continue": "false"})
    condition = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": r"^(\d{7,15})$"})
    nombres = " -> ".join(t.name for t in cadena)
    ET.SubElement(condition, "action", attrib={"application": "log", "data": f"Llamada saliente vía {nombres}"})
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "hangup_after_bridge=true"})
    destinos = "|".join(f"sofia/gateway/{t.name}/${{destination_number}}" for t in cadena)
    ET.SubElement(condition, "action", attrib={"application": "bridge", "data": destinos})


def _append_queue_routes(context: ET.Element, queues: list, record_all: bool = False) -> None:
    """Extensión de entrada de cada cola: contesta y entra a mod_callcenter.
    Si la cola se agota (timeout/sin agentes) o `callcenter` falla, sigue a
    la extensión de desbordamiento (o cuelga si no hay una configurada) —
    igual que el "Fail over destination" de las colas en Issabel/FreePBX.

    `record_all`: si la grabación global YA está prendida, la llamada
    entera se graba desde el contexto de entrada (`_append_recording_hook`)
    y grabar de nuevo acá sería un segundo `record_session` sobre el mismo
    canal. Solo se graba acá cuando `Queue.record` es la ÚNICA razón para
    grabar esta llamada."""
    for queue in queues:
        if not queue.enabled:
            continue
        extension = ET.SubElement(context, "extension", attrib={"name": f"queue_{queue.name}", "continue": "false"})
        condition = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": f"^{queue.extension}$"})
        ET.SubElement(condition, "action", attrib={"application": "answer"})
        if queue.record and not record_all:
            append_record_actions(condition)
        ET.SubElement(condition, "action", attrib={"application": "set", "data": "hangup_after_bridge=false"})
        ET.SubElement(condition, "action", attrib={"application": "callcenter", "data": f"{queue.name}@$${{domain}}"})
        if queue.failover_extension:
            ET.SubElement(condition, "action", attrib={"application": "transfer", "data": f"{queue.failover_extension} XML default"})
        else:
            ET.SubElement(condition, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})


def _append_inbound_routes(public_context: ET.Element, routes: list) -> None:
    """Contexto "public": adonde caen las llamadas entrantes de la troncal
    (ver sip_profiles/external.xml y el context="public" de cada gateway).
    Cada ruta hace matching por DID (número marcado por quien llama) y
    transfiere al contexto "default", reutilizando TODO el ruteo que ya
    existe ahí (extensión → Local_Extension, cola → queue_<nombre>,
    voizbot → bot_<id>) — igual que "Inbound Routes" en Issabel/FreePBX.

    Si ninguna ruta matchea, se cuelga (UNALLOCATED_NUMBER) en vez de
    dejar pasar la llamada a "default" sin control — eso sería un hueco de
    fraude telefónico (un desconocido podría terminar pudiendo marcar
    salientes vía la troncal).
    """
    tag_ext = ET.SubElement(public_context, "extension", attrib={"name": "outside_call_tag", "continue": "true"})
    tag_cond = ET.SubElement(tag_ext, "condition")
    ET.SubElement(tag_cond, "action", attrib={"application": "set", "data": "outside_call=true"})

    # (prioridad, id) y no solo prioridad: dos rutas empatadas en prioridad
    # necesitan un desempate determinístico — sin el id, el orden entre
    # ellas dependía de en qué orden las devolviera la consulta a la base,
    # que no tiene por qué coincidir con el orden que ve el admin en la
    # lista del panel (esa sí ya ordena por (priority, id)).
    ordered = sorted((r for r in routes if r.enabled), key=lambda r: (r.priority, r.id))
    for route in ordered:
        pattern = route.did_pattern.strip()
        expression = ".*" if pattern.lower() in ("any", "*", "") else f"^{pattern}$"
        extension = ET.SubElement(public_context, "extension", attrib={"name": f"did_{route.id}_{route.name}", "continue": "false"})
        condition = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": expression})
        ET.SubElement(condition, "action", attrib={"application": "set", "data": "domain_name=$${domain}"})
        if route.destination_type == "hangup" or not route.destination_value:
            ET.SubElement(condition, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
        else:
            ET.SubElement(condition, "action", attrib={"application": "transfer", "data": f"{route.destination_value} XML default"})

    fallback = ET.SubElement(public_context, "extension", attrib={"name": "no_route", "continue": "false"})
    fb_cond = ET.SubElement(fallback, "condition", attrib={"field": "destination_number", "expression": ".*"})
    ET.SubElement(fb_cond, "action", attrib={"application": "hangup", "data": "UNALLOCATED_NUMBER"})


def _append_recording_hook(context: ET.Element) -> None:
    """Graba TODA llamada del contexto. Va primero y con continue="true"
    para que la llamada siga su ruteo normal después."""
    extension = ET.SubElement(context, "extension", attrib={"name": "nspbx_grabar_todo", "continue": "true"})
    condition = ET.SubElement(extension, "condition")
    append_record_actions(condition)


def _append_call_limits_hook(context: ET.Element, max_minutes: int) -> None:
    """Tope de duración para TODA llamada del contexto — entrante,
    saliente o interna. Va primero, sin condición de "grabar todo" (esa es
    una preferencia de privacidad; esto es protección contra fraude
    telefónico y no depende de ella).

    Sin esto, una extensión comprometida —o simplemente un bug— puede
    dejar una llamada corriendo horas hacia un número caro sin que nadie
    se entere hasta la factura. `execute_on_answer` dispara recién cuando
    el canal contesta de verdad: no cuenta el timbrado.
    """
    if max_minutes <= 0:
        return
    extension = ET.SubElement(context, "extension", attrib={"name": "nspbx_tope_duracion", "continue": "true"})
    condition = ET.SubElement(extension, "condition")
    ET.SubElement(
        condition,
        "action",
        attrib={
            "application": "set",
            "data": f"execute_on_answer=sched_hangup +{max_minutes * 60} alloted_timeout",
        },
    )


def _append_ringback_hook(context: ET.Element) -> None:
    """Sin esto quien llama a una extensión o sale por troncal no oye NADA
    mientras timbra: `bridge`/`originate` solo sintetizan un tono propio si
    la variable de canal `ringback` está seteada, y acá nunca se seteaba —
    confirmado auditando el dialplan completo. Un llamante remoto (PSTN)
    no lo nota, porque su propio conmutador genera el timbre; quien sí se
    queda en silencio es un interno (softphone, otra extensión) o una
    llamada saliente por troncal sin early media real del otro lado.

    `es-ring` (ver vars.xml) en vez de uno propio de Colombia: no hay un
    cadencia oficial ya cargada en esta instalación de FreeSWITCH y es
    preferible una europea real y verificada que inventar una."""
    extension = ET.SubElement(context, "extension", attrib={"name": "nspbx_ringback", "continue": "true"})
    condition = ET.SubElement(extension, "condition")
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "ringback=${es-ring}"})


def _append_call_pickup_feature_code(context: ET.Element) -> None:
    """*8 captura cualquier llamada timbrando en la central, o *8EXT para
    capturar la extensión especificada."""
    pickup = ET.SubElement(context, "extension", attrib={"name": "nspbx_pickup", "continue": "false"})
    c = ET.SubElement(pickup, "condition", attrib={"field": "destination_number", "expression": r"^\*8(\d*)$"})
    ET.SubElement(c, "action", attrib={"application": "answer"})
    ET.SubElement(c, "action", attrib={"application": "pickup", "data": "$1"})


def _append_blacklist_hook(public_context: ET.Element, blacklist: list | None) -> None:
    """Si el caller_id de la llamada entrante está en la lista negra, rechaza inmediatamente."""
    if not blacklist:
        return
    phones = "|".join(b.phone.strip() for b in blacklist if b.phone.strip())
    if not phones:
        return
    ext = ET.SubElement(public_context, "extension", attrib={"name": "nspbx_blacklist", "continue": "false"})
    c = ET.SubElement(ext, "condition", attrib={"field": "caller_id_number", "expression": f"^({phones})$"})
    ET.SubElement(c, "action", attrib={"application": "log", "data": "Llamada bloqueada por Lista Negra"})
    ET.SubElement(c, "action", attrib={"application": "hangup", "data": "CALL_REJECTED"})


def _append_custom_outbound_routes(context: ET.Element, outbound_routes: list | None, trunks: list) -> None:
    """Rutas salientes por patrón de marcado (ej. ^9(\d+)$ o ^3\d{9}$)."""
    if not outbound_routes:
        return
    trunks_by_id = {t.id: t for t in trunks if t.enabled}
    ordered = sorted((r for r in outbound_routes if r.enabled), key=lambda r: (r.priority, r.id))
    for route in ordered:
        patron = route.match_pattern.strip()
        if not patron:
            continue
        extension = ET.SubElement(context, "extension", attrib={"name": f"outbound_route_{route.id}_{route.name}", "continue": "false"})
        condition = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": patron})
        ET.SubElement(condition, "action", attrib={"application": "log", "data": f"Ruta saliente '{route.name}' coincidente"})
        ET.SubElement(condition, "action", attrib={"application": "set", "data": "hangup_after_bridge=true"})

        principal_trunk = trunks_by_id.get(route.trunk_id) if route.trunk_id else None
        cadena = orden_troncales(trunks, principal_id=principal_trunk.id if principal_trunk else None)
        if not cadena:
            continue
        destinos = "|".join(f"sofia/gateway/{t.name}/${{destination_number}}" for t in cadena)
        ET.SubElement(condition, "action", attrib={"application": "bridge", "data": destinos})


def build_dialplan_xml(
    extensions: list,
    bots: list,
    trunks: list | None = None,
    queues: list | None = None,
    inbound_routes: list | None = None,
    record_all: bool = False,
    max_call_minutes: int = 60,
    outbound_routes: list | None = None,
    blacklist: list | None = None,
) -> str:
    """Genera la seccion <section name='dialplan'> completa."""
    root = _e("document", attrib={"type": "freeswitch/xml"})
    section = ET.SubElement(root, "section", attrib={"name": "dialplan"})
    context = ET.SubElement(section, "context", attrib={"name": "default"})

    _append_call_limits_hook(context, max_call_minutes)
    _append_ringback_hook(context)
    if record_all:
        _append_recording_hook(context)
    _append_call_pickup_feature_code(context)
    _append_dnd_feature_codes(context)
    _append_dnd_hook(context, extensions)
    _append_local_extension_route(context, extensions)
    _append_voicebot_routes(section, context, bots, queues, record_all)
    _append_queue_routes(context, queues or [], record_all)

    # Echo test
    echo = ET.SubElement(context, "extension", attrib={"name": "Echo_Test", "continue": "false"})
    c = ET.SubElement(echo, "condition", attrib={"field": "destination_number", "expression": "^9196$"})
    ET.SubElement(c, "action", attrib={"application": "answer"})
    ET.SubElement(c, "action", attrib={"application": "echo"})

    _append_custom_outbound_routes(context, outbound_routes, trunks or [])
    _append_outbound_route(context, trunks or [])

    public_context = ET.SubElement(section, "context", attrib={"name": "public"})
    _append_call_limits_hook(public_context, max_call_minutes)
    if record_all:
        _append_recording_hook(public_context)
    _append_blacklist_hook(public_context, blacklist)
    _append_inbound_routes(public_context, inbound_routes or [])

    return ET.tostring(root, encoding="unicode")

