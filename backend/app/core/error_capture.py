"""Buzón en memoria de los errores (nivel ERROR o peor) que loguea el
backend, para que `app/workers/maintenance.py` los vuelque a la tabla
`system_error_logs` y el chat de diagnóstico (`app/services/ops_assistant.py`)
pueda responder "¿se cayó algo en el sistema?" con hechos.

Antes de esto un `logger.exception(...)` solo existía en stdout (`docker
logs`) — nada quedaba guardado ni era consultable desde el panel.

Nivel ERROR y no WARNING a propósito: hay warnings esperados y ya
manejados en el código (ej. logs_ws.py, "FreeSWITCH no disponible" durante
un reinicio) que ensuciarían las respuestas del chat si se guardaran como
si fueran fallas reales.
"""

import logging
import threading
from datetime import datetime

# Tope de seguridad: si por lo que sea nadie drena el buffer (el worker de
# mantenimiento no arrancó, o está caído), no crece sin límite y se
# empieza a perder lo más viejo en vez de comerse memoria indefinidamente.
_MAX_BUFFER = 500


class _BufferedErrorHandler(logging.Handler):
    def __init__(self, level: int = logging.ERROR):
        super().__init__(level)
        self._buffer: list[dict] = []
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "level": record.levelname,
                "logger_name": record.name,
                "message": self.format(record),
                "traceback": self.formatException(record.exc_info) if record.exc_info else None,
                "created_at": datetime.utcnow(),
            }
        except Exception:
            # Un logging handler que revienta se desinstala solo (Python
            # lo hace por su cuenta) y encima puede volver a llamar a
            # logging para avisarlo — mejor tragarse el error acá.
            return
        with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) > _MAX_BUFFER:
                self._buffer.pop(0)

    def drain(self) -> list[dict]:
        """Se lo lleva TODO y vacía el buffer — pensado para que
        `maintenance.py` lo llame cada minuto y persista lo que haya."""
        with self._lock:
            salida, self._buffer = self._buffer, []
        return salida


error_buffer_handler = _BufferedErrorHandler()


def install() -> None:
    """Cuelga el handler del logger raíz — se llama una sola vez, al
    arrancar el proceso, lo antes posible (ver main.py)."""
    root = logging.getLogger()
    if error_buffer_handler not in root.handlers:
        root.addHandler(error_buffer_handler)
