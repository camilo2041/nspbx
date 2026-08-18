"""Credenciales efímeras para el relay TURN del softphone.

coturn corre con `--use-auth-secret`: no guarda usuarios, valida una
firma. El backend arma un usuario con fecha de vencimiento y lo firma
con el mismo secreto; coturn recalcula la firma y, si coincide y no
venció, deja pasar. Así el navegador nunca recibe el secreto — solo una
credencial que caduca sola y no sirve para nada más.

Es el esquema que coturn documenta como "TURN REST API"
(draft-uberti-behave-turn-rest-00), no un invento nuestro.
"""

import base64
import hashlib
import hmac
import time

from app.core.config import settings

# Servidores STUN públicos de Google: solo sirven para que el navegador
# descubra su propia IP pública. No transportan audio, así que no hay
# nada sensible en usarlos. Se dejan incluso con TURN activo porque ICE
# prueba primero el camino directo, que es más rápido y no consume
# nuestro servidor.
_STUN = {"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}


def ice_servers(usuario: str) -> list[dict]:
    """Lista para `RTCPeerConnection.iceServers` del navegador."""
    if not settings.turn_host or not settings.turn_secret:
        return [_STUN]

    # El usuario es "<vencimiento>:<quien>". coturn parsea la primera
    # parte como epoch y rechaza lo vencido sin consultar nada.
    vence = int(time.time()) + settings.turn_ttl_segundos
    nombre = f"{vence}:{usuario}"
    firma = hmac.new(
        settings.turn_secret.encode(), nombre.encode(), hashlib.sha1
    ).digest()

    return [
        _STUN,
        {
            # "turns:" (con s) y transport=tcp: el navegador abre TLS
            # contra el 443, que es el único puerto que suele estar
            # abierto. Traefik desarma ese TLS por SNI y le pasa el TURN
            # en claro a coturn por la red interna — ver
            # deploy/traefik-dynamic.yml.example.
            "urls": [f"turns:{settings.turn_host}:443?transport=tcp"],
            "username": nombre,
            "credential": base64.b64encode(firma).decode(),
        },
    ]
