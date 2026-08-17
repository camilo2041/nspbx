from datetime import datetime

from app.core.clock import fecha_en_palabras, hora_en_palabras

_FORMATOS_FECHA = (
    "%Y-%m-%d %H:%M",  # 2026-08-21 09:00 (ISO, sin ambigüedad — se prueba primero)
    "%d-%m-%Y %H:%M",  # 21-08-2026 09:00 (día/mes, como se escribe en Colombia)
    "%d-%m-%y %H:%M",  # 21-08-26 09:00
    "%m-%d-%Y %H:%M",  # 08-21-2026 09:00 (mes/día — solo calza si el día no
    "%m-%d-%y %H:%M",  # cabe como mes, ej. 8/21/26; si no, gana día/mes de arriba)
)


def parse_fecha_hora(valor: str) -> datetime | None:
    """Acepta AAAA-MM-DD, DD-MM-AAAA o MM-DD-AAAA (con "/" o "-", año de 2
    o 4 dígitos) — la gente pega fechas de Excel y cada fila puede traer
    un formato distinto según cómo haya escrito la celda. Se prueba
    día/mes primero (convención local) y mes/día solo si el "mes" de esa
    lectura no es un mes válido, así "17/08/2026" y "8/21/26" se leen
    bien las dos sin necesidad de adivinar cuál es cuál.
    None si no trae hora o ningún formato calza — sin hora no hay forma
    de armar una cita sin arriesgar que dos pacientes choquen en el
    mismo horario por defecto."""
    normalizado = " ".join(valor.strip().replace("/", "-").split())
    for formato in _FORMATOS_FECHA:
        try:
            return datetime.strptime(normalizado, formato)
        except ValueError:
            continue
    return None


def formatear_natural(fecha: datetime) -> str:
    """"jueves 21 de agosto a las 9 de la mañana" — para meter en el
    saludo que lee el bot por voz. Sin esto, la fecha cruda ("8/21/26
    9:00") quedaba pegada tal cual en el texto y el TTS la leía número
    por número ("ocho barra veintiuno barra..."), que suena mal y no
    dice la hora de forma natural. Reusa fecha_en_palabras/
    hora_en_palabras (app/core/clock.py) — ya usadas en el resto de la
    conversación del voizbot, en vez de reinventar el mismo formateo acá
    con una variante distinta ("a. m./p. m.") que en una llamada real
    salió leída cortada por el TTS ("a las nueve a.")."""
    return f"{fecha_en_palabras(fecha.date())} a las {hora_en_palabras(fecha)}"
