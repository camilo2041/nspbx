"""Acciones de dialplan para arrancar a grabar una llamada desde un punto
puntual — compartidas por `config_generator.py` (grabación global y de
colas alcanzadas por su propio número) y `flow_engine.py` (colas
alcanzadas desde un nodo "Transferir" del editor de flujo). Vive en su
propio módulo, sin importar nada de ninguno de los dos, porque
`config_generator.py` ya importa `flow_engine.py` — si esto viviera en
cualquiera de los dos, el otro no podría importarlo sin un ciclo."""

import xml.etree.ElementTree as ET


def append_record_actions(condition: ET.Element) -> None:
    """`nspbx_recording` es lo que `/fs/cdr` lee para enlazar el archivo a
    la llamada (ver backend/app/api/calls.py) — usar SIEMPRE este mismo
    mecanismo (nunca el `record-template` propio de mod_callcenter, que no
    queda enlazado a ningún CDR) es lo que permite reproducir cualquier
    grabación desde el panel, venga de la grabación global o de una cola
    puntual."""
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "RECORD_STEREO=false"})
    # Organizadas por fecha (AAAA/MM/DD) en vez de todas sueltas en un solo
    # directorio — con meses de campañas activas, un directorio plano se
    # vuelve imposible de navegar a mano y de acotar por retención.
    dia = "${strftime(%Y)}/${strftime(%m)}/${strftime(%d)}"
    ET.SubElement(
        condition,
        "action",
        attrib={"application": "set", "data": f"nspbx_recording=$${{recordings_dir}}/{dia}/llamada_${{uuid}}.wav"},
    )
    # `record_session` no crea subdirectorios nuevos por su cuenta — hay
    # que asegurarse de que la carpeta del día exista ANTES de grabar.
    # `system` (no `bg_system`) porque record_session, la acción
    # siguiente, necesita que el mkdir ya haya terminado.
    ET.SubElement(
        condition,
        "action",
        attrib={"application": "system", "data": f"mkdir -p $${{recordings_dir}}/{dia}"},
    )
    # `record_session` directo, NO vía execute_on_answer: en las llamadas
    # SALIENTES el canal ya viene contestado cuando entra al dialplan, así
    # que ese disparador no llegaba a ejecutarse nunca y no se generaba
    # ningún archivo (confirmado: el CDR traía la ruta pero el directorio
    # de grabaciones estaba vacío). Graba en segundo plano y no bloquea.
    ET.SubElement(condition, "action", attrib={"application": "record_session", "data": "${nspbx_recording}"})
