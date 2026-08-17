#!/usr/bin/env bash
#
# Prepara una instalación nueva: genera los secretos y los deja
# ESCRITOS EN TODOS LOS ARCHIVOS QUE TIENEN QUE COINCIDIR.
#
# Ese es el motivo de que exista este script y no una lista de pasos
# manuales: FS_XML_SECRET va en tres lugares (.env, xml_curl.conf.xml y
# json_cdr.conf.xml) y FS_ESL_PASSWORD en dos (.env y
# event_socket.conf.xml). Si uno solo queda distinto, el sistema
# arranca igual y falla después, en caliente: sin dialplan, sin
# historial de llamadas o sin control de FreeSWITCH — y el error no
# dice "el secreto no coincide", dice 403 o "conexión rechazada".
#
#   bash scripts/setup.sh
#
# Es idempotente en lo que importa: si ya existe .env, NO lo pisa.

set -euo pipefail
cd "$(dirname "$0")/.."

AUTOLOAD="freeswitch/conf/autoload_configs"

if [ -f .env ]; then
  echo "Ya existe .env — no se toca."
  echo "Si querés regenerar todo desde cero: mové .env a un lado y volvé a correr esto."
  exit 0
fi

# Sin caracteres raros a propósito: estos valores viajan dentro de XML,
# de una URL y de una línea de comando (fs_cli), así que un '&', un '<'
# o una '/' sueltos rompen alguno de los tres usos.
gen() { openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c "${1:-32}"; }

FS_ESL_PASSWORD="$(gen 32)"
FS_XML_SECRET="$(gen 43)"
AUTH_SECRET="$(gen 43)"
POSTGRES_PASSWORD="$(gen 24)"

# El host va SOLO como nombre, sin esquema ni barra ni ruta: se inserta
# literal en la regla Host(`...`) de Traefik. Escrito como una URL
# ("https://x.com/") la regla no coincide con NINGÚN pedido, así que
# todo responde 404 y encima no se emite el certificado — sin ningún
# error que explique por qué. Pasó en una instalación real, por eso se
# normaliza acá en vez de confiar en cómo lo escriba cada uno.
pedir_host() {
  local v
  while true; do
    read -rp "Subdominio del panel (ej. pbx.nspbxdevelop.com): " v
    v="${v#http://}"; v="${v#https://}"   # fuera el esquema
    v="${v%%/*}"                           # fuera la barra y todo lo que siga
    v="${v%%:*}"                           # fuera un puerto si lo pusieron
    v="$(printf '%s' "$v" | tr -d '[:space:]')"
    if printf '%s' "$v" | grep -qE '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}$'; then
      PBX_HOST="$v"
      return
    fi
    echo "  No parece un dominio válido. Escribilo sin https:// y sin barra final."
  done
}
pedir_host
echo "  Se usará: ${PBX_HOST}"

read -rp "Nombre del certificatesResolver del Traefik existente [mi-resuelves-ssl]: " ACME_RESOLVER
ACME_RESOLVER="$(printf '%s' "${ACME_RESOLVER:-mi-resuelves-ssl}" | tr -d '[:space:]')"

cat > .env <<EOF
POSTGRES_USER=nspbx
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=nspbx

FS_ESL_PASSWORD=${FS_ESL_PASSWORD}
FS_XML_SECRET=${FS_XML_SECRET}
AUTH_SECRET=${AUTH_SECRET}

PBX_HOST=${PBX_HOST}
ACME_RESOLVER=${ACME_RESOLVER}

# Vacío: la contraseña del admin se genera en el primer arranque y sale
# en el log --> docker compose logs backend | grep -A5 "Usuario inicial"
ADMIN_PASSWORD=
EOF
chmod 600 .env

# Los tres archivos de FreeSWITCH que llevan secretos, generados desde
# sus plantillas .example con los MISMOS valores del .env.
for f in event_socket.conf.xml xml_curl.conf.xml json_cdr.conf.xml; do
  if [ -f "$AUTOLOAD/$f" ]; then
    echo "  $f ya existe — no se toca."
    continue
  fi
  sed -e "s|REEMPLAZAR_POR_FS_ESL_PASSWORD|${FS_ESL_PASSWORD}|g" \
      -e "s|REEMPLAZAR_POR_FS_XML_SECRET|${FS_XML_SECRET}|g" \
      "$AUTOLOAD/$f.example" > "$AUTOLOAD/$f"
  echo "  $f generado."
done

# Carpetas que el compose monta desde el host. Si no existen, Docker las
# crea como root y después el backend no puede escribir dentro.
mkdir -p backups freeswitch/recordings freeswitch/certs

echo
echo "Listo. Secretos generados y sincronizados en .env y en $AUTOLOAD/."
echo
echo "Antes de levantar, verificá que el DNS de ${PBX_HOST} apunte a este"
echo "servidor con nube GRIS en Cloudflare, y que estén abiertos los"
echo "puertos 80, 443, 5060 (TCP+UDP) y 16384-16584/UDP."
echo
echo "Después:  docker compose up -d --build"
