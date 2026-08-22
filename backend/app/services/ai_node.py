"""Resuelve, para una llamada que un nodo Agente IA del editor de flujo
recibe, el prompt/herramientas/salidas efectivos de ESE nodo — el
equivalente en vivo de lo que antes hacía `ai_intents.obtener()` con la
selección fija de gestión. Vive aparte de `ai_intents.py` (que sigue
prestando `BASE` y las plantillas) y de `flow_engine.py` (que genera el
dialplan) para no crear un import circular entre los dos: flow_engine ya
importa ai_intents para migrar los nodos viejos."""

from dataclasses import dataclass, field

from app.core.clock import calendario
from app.models import VoiceBot
from app.services import ai_intents
from app.services.flow_engine import parse_flow


@dataclass(frozen=True)
class NodoAI:
    node_id: str
    label: str
    prompt: str
    tools: tuple[str, ...]
    max_turns: int
    greeting: str | None
    requiere_cita: bool
    # {razon: node_id} — solo las salidas que además de estar configuradas
    # en el editor (con su label) tienen un edge de verdad conectado.
    exit_targets: dict[str, str] = field(default_factory=dict)
    # [{key, label}, ...] — lo que necesita llm.tools_para para armar el
    # enum de la tool avanzar_flujo.
    exit_options: list[dict] = field(default_factory=list)


def _prompt_efectivo(objetivo: str) -> str:
    """BASE (tono/reglas comunes) + el objetivo propio del nodo + un
    calendario ya resuelto — el modelo calcula mal las fechas de memoria
    (ver el comentario original que traía esta lógica en ai_agent.py)."""
    objetivo = objetivo.strip() or "Atiende lo que la persona necesite y resuélvelo."
    return (
        f"{ai_intents.BASE}\n\n{objetivo}\n\n"
        f"CALENDARIO (úsalo SIEMPRE, nunca calcules fechas de memoria):\n"
        f"{calendario(15)}\n\n"
        "Para interpretar 'mañana', 'el viernes', 'la otra semana', 'en quince días', "
        "busca el día en esa tabla y copia la fecha ISO que le corresponde. Si la "
        "persona pide un día que no aparece, pídele que lo precise en vez de "
        "adivinarlo. Antes de confirmar, di siempre el día de la semana junto a la "
        "fecha ('el viernes 21') para que pueda corregirte si no coincide.\n"
        "Al llamar herramientas, las fechas SIEMPRE en formato YYYY-MM-DD y las horas en HH:MM (24h)."
    )


async def cargar(db, bot_id: int, node_id: str) -> NodoAI | None:
    """None si el bot no existe, no tiene flujo, o el nodo ya no está (p.
    ej. se borró del editor entre que se generó el dialplan y esta llamada
    llegó a tocarlo) — el llamador decide cómo fallar (ver ai_agent.py)."""
    bot = await db.get(VoiceBot, bot_id)
    if not bot:
        return None
    flow = parse_flow(bot.flow_json)
    if not flow:
        return None
    node = next((n for n in flow["nodes"] if str(n.get("id")) == str(node_id)), None)
    if not node or node.get("type") != "ai_agent":
        return None

    data = node.get("data") or {}
    configuradas = {
        str(e.get("key", "")).strip(): str(e.get("label", "")).strip()
        for e in (data.get("exits") or [])
        if str(e.get("key", "")).strip()
    }
    exit_targets = {
        str(edge.get("sourceHandle", "")).strip(): str(edge.get("target"))
        for edge in flow["edges"]
        if str(edge.get("source")) == str(node_id) and str(edge.get("sourceHandle", "")).strip() in configuradas
    }
    exit_options = [{"key": k, "label": configuradas[k]} for k in exit_targets]

    return NodoAI(
        node_id=str(node_id),
        label=str(data.get("label") or "Agente IA"),
        prompt=_prompt_efectivo(str(data.get("prompt") or "")),
        tools=tuple(data.get("tools") or ()),
        max_turns=int(data.get("max_turns") or 12),
        greeting=(str(data.get("greeting")).strip() or None) if data.get("greeting") else None,
        requiere_cita=bool(data.get("requiere_cita")),
        exit_targets=exit_targets,
        exit_options=exit_options,
    )
