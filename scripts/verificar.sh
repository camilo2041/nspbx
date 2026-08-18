#!/usr/bin/env bash
#
# Chequeo completo de una instalación: contenedores, secretos, base,
# ESL, troncales, ruteo por Traefik y certificado.
#
#   bash scripts/verificar.sh
#
# Cada línea dice qué se probó y contra qué. No "arregla" nada: solo
# reporta, para poder correrlo tranquilo en producción.

cd "$(dirname "$0")/.."
AUTOLOAD="freeswitch/conf/autoload_configs"
FALLAS=0

ok()    { printf '  \033[32m✓\033[0m %s\n' "$1"; }
falla() { printf '  \033[31m✗\033[0m %s\n' "$1"; FALLAS=$((FALLAS+1)); }
aviso() { printf '  \033[33m!\033[0m %s\n' "$1"; }
titulo(){ printf '\n\033[1m%s\033[0m\n' "$1"; }

titulo "1. Contenedores"
for c in nspbx_postgres nspbx_backend nspbx_voicebot nspbx_freeswitch nspbx_frontend; do
  ESTADO=$(docker inspect "$c" --format '{{.State.Health.Status}}' 2>/dev/null || echo "ausente")
  case "$ESTADO" in
    healthy) ok "$c" ;;
    ausente) falla "$c no existe" ;;
    *)       falla "$c está '$ESTADO'" ;;
  esac
done

titulo "2. Secretos sincronizados"
# La causa nº1 de fallas silenciosas: el mismo valor tiene que estar
# repetido idéntico en varios archivos. Si no coincide, el sistema
# arranca igual y falla después con 403 o "conexión rechazada".
ESL_ENV=$(grep '^FS_ESL_PASSWORD=' .env 2>/dev/null | cut -d= -f2-)
ESL_XML=$(grep -oE 'name="password" value="[^"]+"' "$AUTOLOAD/event_socket.conf.xml" 2>/dev/null | sed 's/.*value="//;s/"//')
XML_ENV=$(grep '^FS_XML_SECRET=' .env 2>/dev/null | cut -d= -f2-)
XML_CURL=$(grep -oE 'secret=[A-Za-z0-9]+' "$AUTOLOAD/xml_curl.conf.xml" 2>/dev/null | head -1 | cut -d= -f2)
XML_CDR=$(grep -oE '/fs/cdr/[A-Za-z0-9]+' "$AUTOLOAD/json_cdr.conf.xml" 2>/dev/null | cut -d/ -f4)

[ -n "$ESL_ENV" ] && [ "$ESL_ENV" = "$ESL_XML" ] \
  && ok "clave ESL: .env == event_socket.conf.xml" \
  || falla "clave ESL NO coincide entre .env y event_socket.conf.xml"

if [ -n "$XML_ENV" ] && [ "$XML_ENV" = "$XML_CURL" ] && [ "$XML_ENV" = "$XML_CDR" ]; then
  ok "secreto XML: .env == xml_curl == json_cdr"
else
  falla "secreto XML NO coincide (.env=${XML_ENV:0:8}… xml_curl=${XML_CURL:0:8}… json_cdr=${XML_CDR:0:8}…)"
fi

titulo "3. IP pública anunciada"
# El fallo más caro de diagnosticar de toda la migración: vars.xml venía
# con la IP del servidor anterior, FreeSWITCH la anunciaba en el Contact,
# el proveedor respondía a una dirección ajena y el REGISTER moría por
# timeout mostrando un 503 que no menciona nada de esto.
IP_REAL=$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null)
# Solo las líneas X-PRE-PROCESS reales: los comentarios del archivo traen
# ejemplos como data="external_rtp_ip=1.2.3.4" y un grep suelto los
# tomaría como si fueran la configuración vigente.
IP_CFG=$(grep -oE '<X-PRE-PROCESS[^>]*external_sip_ip=[^"]+' freeswitch/conf/vars.xml 2>/dev/null | sed 's/.*external_sip_ip=//')
if [ -z "$IP_CFG" ]; then
  falla "no se pudo leer external_sip_ip de vars.xml"
elif [ "$IP_CFG" = "REEMPLAZAR_POR_IP_PUBLICA" ]; then
  falla "vars.xml sin configurar — corré: bash scripts/setup.sh"
elif [ -n "$IP_REAL" ] && [ "$IP_CFG" != "$IP_REAL" ]; then
  falla "vars.xml anuncia $IP_CFG pero la IP real es $IP_REAL (¿se movió de servidor?)"
else
  ok "vars.xml anuncia la IP correcta ($IP_CFG)"
fi

titulo "4. Base de datos"
if docker exec nspbx_postgres pg_isready -U "${POSTGRES_USER:-nspbx}" >/dev/null 2>&1; then
  ok "postgres acepta conexiones"
  for t in users extensions trunks appointments call_logs; do
    N=$(docker exec nspbx_postgres psql -U "${POSTGRES_USER:-nspbx}" -d "${POSTGRES_DB:-nspbx}" -t -A -c "SELECT count(*) FROM $t;" 2>/dev/null)
    [ -n "$N" ] && ok "tabla $t: $N registro(s)" || falla "no se pudo leer la tabla $t"
  done
else
  falla "postgres no responde"
fi

titulo "5. FreeSWITCH (ESL) y troncales"
ESL_OUT=$(docker exec nspbx_backend python -c "
import asyncio,sys; sys.path.insert(0,'/app')
from app.services import esl
from app.core.database import async_session
from app.models import Trunk
from sqlalchemy import select
async def m():
    st = await esl.status()
    print('VERSION', st.get('version','?')[:30])
    print('SESIONES', st.get('current_sessions','?'))
    async with async_session() as s:
        ts=(await s.execute(select(Trunk))).scalars().all()
    for t in ts:
        g=await esl.gateway_status(t.name)
        print('TRUNK', t.name, g.get('state'))
asyncio.run(m())
" 2>/dev/null)

if [ -n "$ESL_OUT" ]; then
  ok "ESL responde ($(echo "$ESL_OUT" | grep VERSION | cut -d' ' -f2-))"
  ok "llamadas activas: $(echo "$ESL_OUT" | grep SESIONES | awk '{print $2}')"
  if echo "$ESL_OUT" | grep -q TRUNK; then
    echo "$ESL_OUT" | grep TRUNK | while read -r _ N E; do
      [ "$E" = "REGED" ] && ok "troncal $N registrada" || falla "troncal $N en estado '$E'"
    done
  else
    aviso "no hay troncales cargadas todavía"
  fi
else
  falla "el backend no puede hablar con FreeSWITCH por ESL"
fi

titulo "6. Publicación web"
HOST=$(grep '^PBX_HOST=' .env 2>/dev/null | cut -d= -f2-)
if [ -z "$HOST" ]; then
  aviso "PBX_HOST no está en .env — se omite el chequeo web"
else
  case "$HOST" in
    *://*|*/*) falla "PBX_HOST mal escrito ('$HOST'): va solo el dominio, sin https:// ni barra" ;;
  esac
  P=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$HOST/")
  A=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$HOST/api/auth/me")
  [ "$P" = "200" ] || [ "$P" = "307" ] && ok "panel responde ($P)" || falla "panel devolvió $P"
  # 401 es lo correcto: el backend contesta y rechaza por falta de sesión.
  [ "$A" = "401" ] && ok "API responde y exige sesión (401)" || falla "API devolvió $A (se esperaba 401)"
  # Sin -k: si esto funciona, el certificado es de verdad y no de staging.
  if curl -s -o /dev/null --max-time 10 "https://$HOST/" 2>/dev/null; then
    ok "certificado válido y confiable"
  else
    aviso "certificado NO confiable — ¿sigue el caserver de staging en Traefik?"
  fi
  # /fs/* no debe ser alcanzable desde internet.
  F=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$HOST/fs/cdr/x")
  [ "$F" = "404" ] && ok "/fs/* no expuesto (404)" || aviso "/fs/* devolvió $F — debería ser 404"
fi

titulo "Resultado"
if [ "$FALLAS" -eq 0 ]; then
  printf '  \033[32mTodo en orden.\033[0m\n\n'
else
  printf '  \033[31m%s comprobación(es) fallaron.\033[0m\n\n' "$FALLAS"
  exit 1
fi
