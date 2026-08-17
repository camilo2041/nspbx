"""Sustitución de {variables} en el mensaje de apertura de una campaña de
confirmación. A propósito NO usa `str.format`: un signo { suelto que se le
haya escapado a alguien en el texto (o una variable que no se cargó para
ese número) reventaría la llamada entera con un KeyError/ValueError en
vez de decir la frase igual con lo que sí tiene."""

import re

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render(template: str, variables: dict[str, str]) -> str:
    """Reemplaza cada {nombre} por su valor en `variables`. Lo que no
    tenga valor cargado se deja tal cual (visible, para que sea obvio en
    una prueba que faltó esa columna al cargar el número)."""
    return _PLACEHOLDER.sub(lambda m: variables.get(m.group(1), m.group(0)), template)
