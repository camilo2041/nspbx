#!/usr/bin/env bash
#
# Descarga la biblioteca de sonidos oficial de FreeSWITCH.
#
#   bash scripts/sonidos.sh
#
# ¿Por qué no están en el repositorio? Son ~32 MB de audio que nunca
# cambian; meterlos en git haría pesado cada clone para siempre. Y ¿por
# qué no en la imagen de Docker? Porque docker-compose.yml monta
# ./freeswitch/sounds ENCIMA de /usr/share/freeswitch/sounds, así que
# cualquier cosa instalada ahí durante el build queda tapada al arrancar.
#
# Qué trae y para qué:
#
#   music/8000        Música en espera. Sin esto, hold_music apunta a
#                     local_stream://moh -> una carpeta inexistente, y
#                     quien quede en espera escucha silencio absoluto.
#
#   en/us/callie      Las frases y números grabados que usan voicemail,
#                     los menús IVR y la aplicación `say` ("marque uno",
#                     "su mensaje ha sido guardado", los dígitos...).
#                     El sistema HOY no las usa —el dialplan resuelve
#                     todo con audio propio de los bots y con flite— así
#                     que sin ellas nada se rompe. Hacen falta el día
#                     que se agregue buzón de voz o un IVR con frases
#                     estándar, y entonces el fallo es silencioso: la
#                     llamada sigue como si el audio se hubiera
#                     reproducido.
#
# Solo se bajan los paquetes de 8000 Hz porque global_codec_prefs es
# "PCMU,PCMA,G722" y los dos primeros —los que se negocian casi siempre—
# trabajan a 8 kHz. Si alguna vez G722 pasa a ser el habitual, existen
# los mismos tarballs en 16000 y basta con agregarlos acá: FreeSWITCH
# elige la carpeta por frecuencia y, si no la encuentra, remuestrea la
# que haya (por eso en el log aparece "Can't open directory .../16000"
# como aviso y no como error).
#
# Es idempotente: lo que ya está no se vuelve a bajar.

set -euo pipefail
cd "$(dirname "$0")/.."

DEST="freeswitch/sounds"
BASE="https://files.freeswitch.org/releases/sounds"

# Versiones fijas y no "latest" a propósito: así dos instalaciones del
# mismo commit tienen exactamente los mismos archivos.
MUSICA="freeswitch-sounds-music-8000-1.0.52.tar.gz"
VOCES="freeswitch-sounds-en-us-callie-8000-1.0.51.tar.gz"

mkdir -p "$DEST"

bajar() {
  local archivo="$1" marca="$2" descripcion="$3"
  if [ -d "$DEST/$marca" ]; then
    echo "  $descripcion: ya está ($marca) — se omite."
    return
  fi
  echo "  $descripcion: descargando $archivo…"
  # Al mismo directorio de destino: los tarballs oficiales ya vienen con
  # la estructura correcta adentro (music/8000/..., en/us/callie/...).
  if ! curl -fL --progress-bar "$BASE/$archivo" | tar -xz -C "$DEST"; then
    echo "  ERROR bajando $archivo — revisá la salida a internet." >&2
    return 1
  fi
  echo "  $descripcion: listo."
}

echo "Sonidos de FreeSWITCH -> $DEST"
bajar "$MUSICA" "music"  "Música en espera"
bajar "$VOCES"  "en"     "Voces en inglés (callie)"

echo
echo "Listo. Para que FreeSWITCH los tome:"
echo "  docker compose restart freeswitch"
