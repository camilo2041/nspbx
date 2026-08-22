import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy import select, update

from app.core.database import async_session
from app.models import Campaign, CampaignNumber, SystemSettings, Trunk, VoiceBot
from app.services import esl, templating
from app.services.fechas import formatear_natural, parse_fecha_hora
from app.services.config_generator import orden_troncales

logger = logging.getLogger(__name__)


class CampaignDialer:
    """Autodialer: procesa números pendientes de campañas con limite de concurrencia."""

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None
        self._active: dict[int, int] = {}  # campaign_id -> llamadas activas
        self._dial_tasks: set[asyncio.Task] = set()

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("CampaignDialer iniciado")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Las llamadas en curso (_dial) quedaban huérfanas: se cancelaban
        # sin llegar a su bloque finally, dejando números en "dialing" para
        # siempre y contadores de concurrencia desincronizados. Se espera
        # a que terminen limpio (o se cancelan tras un margen) antes de
        # devolver el control.
        if self._dial_tasks:
            pending = list(self._dial_tasks)
            done, pending_after = await asyncio.wait(pending, timeout=10)
            for task in pending_after:
                task.cancel()
            if pending_after:
                await asyncio.gather(*pending_after, return_exceptions=True)
        logger.info("CampaignDialer detenido")

    async def _loop(self):
        while self._running:
            try:
                await self._process_once()
            except Exception:
                logger.exception("Error en CampaignDialer loop")
            await asyncio.sleep(2)

    async def _process_once(self):
        async with async_session() as session:
            # Tope GLOBAL, no solo por campaña: antes cada campaña respetaba
            # su propio max_concurrency, pero nada impedía que dos
            # campañas a la vez (o una campaña más tráfico entrante y
            # llamadas de click-to-call) superaran lo que la troncal real
            # soporta — y ahí el proveedor empieza a rechazar TODO,
            # entrantes incluidas. Se mide contra los canales REALES de
            # FreeSWITCH (current_sessions cuenta ambas patas de cada
            # llamada bridgeada, no solo las de campañas), no contra un
            # contador propio que podría desincronizarse.
            settings_row = await session.get(SystemSettings, 1)
            tope_global = settings_row.max_concurrent_calls if settings_row else 20

            try:
                estado = await esl.status()
                margen_global = tope_global - estado.get("current_sessions", 0)
            except Exception:
                # Si no se puede consultar FreeSWITCH, mejor no marcar
                # nada este ciclo que arriesgarse a pasar el tope a ciegas.
                logger.warning("No se pudo consultar el estado de FreeSWITCH; se salta este ciclo de marcado")
                return
            if margen_global <= 0:
                return

            result = await session.execute(
                select(Campaign).where(Campaign.status == "running")
            )
            campaigns = result.scalars().all()
            for campaign in campaigns:
                if margen_global <= 0:
                    break
                active = self._active.get(campaign.id, 0)
                slots = min(campaign.max_concurrency - active, margen_global)
                if slots <= 0:
                    continue
                numbers = await session.execute(
                    select(CampaignNumber)
                    .where(
                        CampaignNumber.campaign_id == campaign.id,
                        CampaignNumber.status == "pending",
                    )
                    .limit(slots)
                )
                numbers_list = list(numbers.scalars().all())
                margen_global -= len(numbers_list)
                for number in numbers_list:
                    number.status = "dialing"
                    number.attempts += 1
                await session.commit()
                for number in numbers_list:
                    task = asyncio.create_task(self._dial(session, campaign, number))
                    self._dial_tasks.add(task)
                    task.add_done_callback(self._dial_tasks.discard)

    async def _dial(self, session, campaign: Campaign, number: CampaignNumber):
        self._active[campaign.id] = self._active.get(campaign.id, 0) + 1
        try:
            async with async_session() as s:
                fresh = await s.get(Campaign, campaign.id)
                trunk = await s.get(Trunk, fresh.trunk_id) if fresh.trunk_id else None
                bot = await s.get(VoiceBot, fresh.voicebot_id) if fresh.voicebot_id else None
                todas_troncales = (await s.execute(select(Trunk))).scalars().all()
            if not trunk or not trunk.enabled:
                raise RuntimeError("Campaña sin troncal habilitado")
            exten = f"bot_{bot.id}" if bot and bot.enabled else None

            # Campaña de confirmación de citas: si tiene una frase de
            # apertura propia (campañas viejas, de antes de simplificar
            # esto — ver api/campaigns.py), se arma ACÁ con las variables
            # de este número. Si no tiene, el bot abre con el saludo que
            # ya tiene configurado su propio nodo Agente IA — no hace falta
            # nada especial acá para eso.
            extra_vars: dict[str, str] = {}
            if fresh.message_template and number.extra_data:
                variables = json.loads(number.extra_data)
                # La fecha llega tal cual la escribió quien cargó la
                # campaña ("8/21/26 9:00") — si se metiera cruda en el
                # saludo, el TTS la lee número por número en vez de decir
                # algo natural. Se reformatea a texto hablado ("jueves 21
                # de agosto a las 9:00 a. m.") solo para la voz; si no se
                # puede leer como fecha, se deja el texto original tal
                # cual (puede que ya venga en un formato hablado).
                if "fecha" in variables:
                    fecha_dt = parse_fecha_hora(variables["fecha"])
                    if fecha_dt:
                        variables["fecha"] = formatear_natural(fecha_dt)
                extra_vars["nspbx_greeting"] = templating.render(fresh.message_template, variables)
            # La cita EXACTA (ver _sincronizar_agenda en api/campaigns.py) —
            # así confirmar_cita/cancelar_cita/reagendar_cita actúan sobre
            # esta cita puntual y no adivinan "la próxima confirmada de
            # este teléfono", que falla si el mismo número tiene más de una
            # cita a la vez. También es la señal que usa flow_engine.py
            # para saltarse el menú y entrar directo al nodo Agente IA de
            # campaña — por eso va SIEMPRE que haya cita, sin importar si
            # esta campaña tiene o no una frase de apertura propia (antes
            # dependía de eso, y una campaña sin frase nunca entraba
            # directo a la IA aunque tuviera la cita bien sincronizada).
            if number.appointment_id:
                extra_vars["nspbx_appointment_id"] = str(number.appointment_id)

            # La troncal elegida para la campaña va primero; si hay otras
            # habilitadas, quedan como respaldo — si esa no contesta o la
            # rechaza, FreeSWITCH prueba la siguiente sola, sin que la
            # campaña pierda el número por una troncal caída.
            #
            # OJO: FreeSWITCH solo interpreta el bloque {var=val,...} que
            # va INMEDIATAMENTE tras "originate " (el del primer tramo);
            # en cualquier tramo siguiente de una cadena separada por "|"
            # ese bloque NO se parsea como variables — queda pegado al
            # nombre del canal ("{origination_caller_id_number=X}sofia")
            # y FreeSWITCH revienta con CHAN_NOT_IMPLEMENTED ("Could not
            # locate channel type ...") porque busca un módulo con ese
            # nombre literal. Verificado en vivo con fs_cli probando cada
            # combinación. Por eso el caller ID va UNA sola vez en el
            # bloque global (se aplica a todos los tramos por igual) y
            # cada tramo queda como texto plano, sin su propio {}.
            cadena = orden_troncales(todas_troncales, principal_id=trunk.id)
            cid_global = trunk.caller_id_number or trunk.username
            if cid_global:
                extra_vars["origination_caller_id_number"] = cid_global
            tramos = [f"sofia/gateway/{t.name}/{number.phone}" for t in cadena]

            await esl.originate(
                dest=number.phone,
                endpoint=tramos,
                caller_id="NSPBX",
                timeout=30,
                exten=exten,
                wait_timeout=30 * len(tramos) + 15,
                extra_vars=extra_vars or None,
            )
            async with async_session() as s:
                await s.execute(
                    update(CampaignNumber)
                    .where(CampaignNumber.id == number.id)
                    .values(status="done")
                )
                await s.commit()
        except Exception as exc:
            logger.warning("Fallo al marcar %s: %s", number.phone, exc)
            cause = str(exc).upper()
            final_status = "failed"
            if "USER_BUSY" in cause:
                final_status = "busy"
            elif "NO_ANSWER" in cause or "NO_USER_RESPONSE" in cause or "ORIGINATOR_CANCEL" in cause:
                final_status = "noanswer"
            async with async_session() as s:
                target = await s.get(CampaignNumber, number.id)
                fresh = await s.get(Campaign, campaign.id)
                if target:
                    target.last_error = str(exc)[:500]
                    if target.attempts > (fresh.retries if fresh else 0):
                        target.status = final_status
                    else:
                        target.status = "pending"
                    await s.commit()
        finally:
            self._active[campaign.id] = max(0, self._active.get(campaign.id, 0) - 1)
            await self._maybe_finish(campaign.id)

    async def _maybe_finish(self, campaign_id: int):
        async with async_session() as session:
            remaining = await session.execute(
                select(CampaignNumber.id)
                .where(
                    CampaignNumber.campaign_id == campaign_id,
                    CampaignNumber.status.in_(["pending", "dialing"]),
                )
                .limit(1)
            )
            if not remaining.first():
                await session.execute(
                    update(Campaign)
                    .where(Campaign.id == campaign_id)
                    .values(status="done", finished_at=datetime.utcnow())
                )
                await session.commit()


dialer = CampaignDialer()
