"""Autodetección de direcciones IP — para que el panel de Ajustes se
pueda configurar solo en vez de que alguien tenga que buscar la IP a mano
(como pasó en producción: la IP LAN cambió de red y quedó vieja en la
config durante días sin que nadie lo notara)."""

import ipaddress
import logging
import socket

import httpx

logger = logging.getLogger(__name__)


def lan_ip() -> str | None:
    """IP de red local por la que este contenedor saldría a internet —
    la misma técnica que usa FreeSWITCH para su propia autodetección: abrir
    un socket UDP "conectado" a una IP pública no envía ningún paquete,
    solo le pregunta al sistema operativo qué interfaz usaría."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


async def public_ip() -> str | None:
    """IP pública real vista desde afuera. Puede no coincidir con la IP
    que anuncia FreeSWITCH a los troncales si esa quedó vieja — de ahí que
    el diagnóstico las muestre una al lado de la otra."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://api.ipify.org")
            r.raise_for_status()
            return r.text.strip()
    except Exception:
        logger.warning("No se pudo detectar la IP pública", exc_info=True)
        return None


def ip_parece_no_alcanzable(ip: str | None) -> bool:
    """True si esta IP nunca podría recibir tráfico real de internet:
    privada (RFC 1918), loopback, o CGNAT (100.64.0.0/10 — común en
    conexiones residenciales sin IP pública propia). Anunciarla a un
    proveedor de troncal SIP como dirección de contacto dejaba el
    registro en "REGED" (el proveedor no valida esto) pero ninguna
    llamada entrante lograba completarse — el bug que motivó este chequeo."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return True
    return addr in ipaddress.ip_network("100.64.0.0/10")
