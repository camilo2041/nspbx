"""Hora local del negocio, en un solo lugar.

Todo lo que tiene que ver con la agenda (horario de atención 8:00-18:00,
"hoy", "mañana", si un cupo ya pasó) está expresado en hora de Colombia,
pero el contenedor corre en UTC. Mezclar ambas cosas rompía la agenda de
forma silenciosa: `available_slots` comparaba un reloj local contra
`datetime.utcnow()`, así que a las 11:36 de Colombia (16:36 UTC) escondía
toda la mañana, y pasada la 1 pm local respondía que no quedaba ningún
cupo en todo el día. `find_next_appointment` tenía el mismo defecto y no
encontraba una cita de las 10:00 hasta pasadas las 6 am.

Las citas se guardan como datetime SIN zona, y ese naive significa
SIEMPRE hora local del negocio. `now_local()` devuelve el "ahora" en esa
misma escala para que las comparaciones sean válidas, sin depender de la
variable TZ del contenedor.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
DOMINGO = 6


def business_tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def now_local() -> datetime:
    """El "ahora" del negocio, naive, en la misma escala que
    `Appointment.appointment_date`."""
    return datetime.now(business_tz()).replace(tzinfo=None)


def a_hora_local(dt: datetime) -> datetime:
    """Deja cualquier fecha en la escala del negocio: naive y local.

    El navegador manda las fechas en UTC con sufijo Z (`toISOString()`), y
    Pydantic las convierte en datetime CON zona. Si una de esas llega a la
    capa de agenda, compararla contra las fechas naive de la base tira
    `can't compare offset-naive and offset-aware datetimes` y la petición
    muere con un 500 — pasaba al crear una cita en un día que ya tuviera
    otra. Además, sin convertir, una cita de las 10:00 quedaba guardada a
    las 15:00. Se normaliza en el borde para que adentro todo sea naive."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(business_tz()).replace(tzinfo=None)


def fecha_en_palabras(d: date) -> str:
    """"viernes 21 de agosto" — para decirla en voz alta y para que el
    modelo vea siempre el día de la semana junto a la fecha."""
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def hora_en_palabras(dt: datetime) -> str:
    """"3 de la tarde" en vez de "15:00".

    El texto va a un sintetizador de voz: leído tal cual, "15:00" sale
    como "quince cero cero", que no es como habla una recepcionista."""
    h, m = dt.hour, dt.minute
    franja = "de la mañana" if h < 12 else "de la tarde" if h < 19 else "de la noche"
    h12 = h if 1 <= h <= 12 else abs(h - 12) or 12
    if m == 0:
        return f"{h12} {franja}"
    if m == 30:
        return f"{h12} y media {franja}"
    return f"{h12} y {m} {franja}"


def calendario(dias: int = 15) -> str:
    """Tabla de fechas próximas para meter en el prompt.

    El modelo calculaba mal la aritmética de calendario: en una llamada
    real el paciente pidió "el viernes de la próxima semana" y agendó el
    18, que era martes. Los LLM son malos contando días, así que en vez de
    pedirle que calcule se le da la equivalencia ya resuelta y solo tiene
    que buscarla."""
    hoy = now_local().date()
    # Lunes de la semana en curso. "Próxima semana" es la que arranca el
    # lunes siguiente: sin marcarlo, el modelo tiene que deducirlo y falla
    # — pedirle "el viernes de la próxima semana" un domingo le dio el
    # viernes de dos semanas después.
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    etiqueta_semana = {0: "esta semana", 1: "PRÓXIMA semana", 2: "en dos semanas"}

    filas = []
    for i in range(dias):
        d = hoy + timedelta(days=i)
        semana = ((d - timedelta(days=d.weekday())) - lunes_actual).days // 7
        nota = f"  [{etiqueta_semana.get(semana, f'en {semana} semanas')}]"
        if i == 0:
            nota += "  <- HOY"
        elif i == 1:
            nota += "  <- mañana"
        if d.weekday() == DOMINGO:
            nota += "  (domingo, cerrado)"
        filas.append(f"{fecha_en_palabras(d)} = {d.isoformat()}{nota}")
    return "\n".join(filas)
