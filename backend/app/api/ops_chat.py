"""Chat de diagnóstico en vivo — la versión conversacional de ir pantalla
por pantalla (Llamadas, Ajustes > Diagnóstico, Consumo IA) cruzando datos
a mano. Vive fuera de /api/ (como /ws/logs) porque un WebSocket de
navegador no puede mandar la cabecera Authorization en el handshake: el
token viaja por query string y se valida acá a mano, con el mismo
criterio que el resto de la API (ver app/core/auth.py).

El motor real (qué herramientas existen, cómo arma la respuesta) vive en
app/services/ops_assistant.py — acá solo se resuelve el usuario, se
mantiene la conversación de ESTA conexión en memoria, y se maneja el
protocolo del socket."""

import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import usuario_desde_token_ws
from app.core.database import get_session
from app.services import ops_assistant

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/ops-chat")
async def ops_chat_websocket(websocket: WebSocket, session: AsyncSession = Depends(get_session)):
    usuario = await usuario_desde_token_ws(websocket.query_params.get("token"), session)
    # Mismo nivel que el resto de Ajustes/Diagnóstico: este chat puede
    # contar estado interno del backend y de las troncales, tan sensible
    # como esas pantallas.
    if not usuario or not permissions.puede(usuario.role, permissions.AJUSTES_GESTIONAR):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    # Historial en memoria de ESTA conexión — se reinicia si se reconecta,
    # como cualquier consola de chat; no hay necesidad de persistirlo.
    messages: list[dict] = [{"role": "system", "content": ops_assistant.SYSTEM_PROMPT}]

    try:
        while True:
            payload = await websocket.receive_json()
            texto = str(payload.get("text", "")).strip()
            if not texto:
                continue

            messages.append({"role": "user", "content": texto})
            await websocket.send_json({"type": "thinking"})

            try:
                respuesta = await ops_assistant.responder(messages, usuario)
            except ValueError as exc:
                # Falta configurar la API key del modelo, etc. — no es un
                # error del sistema, es de configuración: no se quiere el
                # traceback, y el turno del usuario se descarta del
                # historial para que pueda reintentar sin arrastrar un
                # mensaje sin respuesta real.
                messages.pop()
                await websocket.send_json({"type": "error", "text": str(exc)})
                continue

            messages.append({"role": "assistant", "content": respuesta})
            await websocket.send_json({"type": "answer", "text": respuesta})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Chat de diagnóstico: error en la conversación de %s", usuario.username)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
