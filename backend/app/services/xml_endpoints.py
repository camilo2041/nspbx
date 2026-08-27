import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Guardia compartido con /fs/cdr (app/api/calls.py) — ver el porqué en su
# docstring; antes vivía acá y ese otro endpoint quedó sin protección.
from app.core.auth import verificar_secreto_fs as _verificar_secreto
from app.core.database import get_session
from app.models import BlacklistNumber, Extension, InboundRoute, OutboundRoute, PriorityNumber, Queue, RingGroup, SystemSettings, TimeCondition, TimeGroup, Trunk, VoiceBot
from app.services.config_generator import build_dialplan_xml, build_directory_xml

logger = logging.getLogger(__name__)

router = APIRouter(tags=["freeswitch-xml"])


@router.get("/fs/directory", dependencies=[Depends(_verificar_secreto)])
async def fs_directory(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Extension).where(Extension.enabled.is_(True)))
    extensions = result.scalars().all()
    rg_result = await session.execute(select(RingGroup))
    ring_groups = rg_result.scalars().all()
    xml = build_directory_xml(extensions, ring_groups)
    return Response(content=xml, media_type="text/xml")


@router.get("/fs/dialplan", dependencies=[Depends(_verificar_secreto)])
async def fs_dialplan(session: AsyncSession = Depends(get_session)):
    ext_result = await session.execute(select(Extension).where(Extension.enabled.is_(True)))
    extensions = ext_result.scalars().all()
    bot_result = await session.execute(select(VoiceBot).where(VoiceBot.enabled.is_(True)))
    bots = bot_result.scalars().all()
    trunk_result = await session.execute(select(Trunk).where(Trunk.enabled.is_(True)).order_by(Trunk.id))
    trunks = trunk_result.scalars().all()
    queue_result = await session.execute(select(Queue).where(Queue.enabled.is_(True)))
    queues = queue_result.scalars().all()
    route_result = await session.execute(select(InboundRoute).where(InboundRoute.enabled.is_(True)))
    inbound_routes = route_result.scalars().all()
    outbound_result = await session.execute(select(OutboundRoute).where(OutboundRoute.enabled.is_(True)).order_by(OutboundRoute.priority, OutboundRoute.id))
    outbound_routes = outbound_result.scalars().all()
    blacklist_result = await session.execute(select(BlacklistNumber))
    blacklist = blacklist_result.scalars().all()
    priority_result = await session.execute(select(PriorityNumber))
    priority_numbers = priority_result.scalars().all()
    tc_result = await session.execute(select(TimeCondition).where(TimeCondition.enabled.is_(True)))
    time_conditions = tc_result.scalars().all()
    tg_result = await session.execute(select(TimeGroup))
    time_groups = tg_result.scalars().all()
    rg_result = await session.execute(select(RingGroup))
    ring_groups = rg_result.scalars().all()
    settings_row = await session.get(SystemSettings, 1)
    record_all = bool(settings_row and settings_row.record_all_calls)
    max_call_minutes = settings_row.max_call_duration_minutes if settings_row else 60
    max_concurrent_calls = settings_row.max_concurrent_calls if settings_row else 0
    priority_announce_text = (settings_row.priority_announce_text if settings_row else None) or ""
    xml = build_dialplan_xml(
        extensions,
        bots,
        trunks,
        queues,
        inbound_routes,
        record_all,
        max_call_minutes,
        max_concurrent_calls=max_concurrent_calls,
        outbound_routes=outbound_routes,
        blacklist=blacklist,
        priority_numbers=priority_numbers,
        priority_announce_text=priority_announce_text,
        time_conditions=time_conditions,
        time_groups=time_groups,
        ring_groups=ring_groups,
    )
    return Response(content=xml, media_type="text/xml")

