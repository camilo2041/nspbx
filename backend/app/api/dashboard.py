"""Dashboard del call center: agregaciones de CDR y de uso IA para los
gráficos del panel (app/call-center/page.tsx). Todo se calcula acá en
Postgres (grupos, sumas, promedios) y el front solo dibuja.

Solo lo ven quienes pueden ver TODAS las llamadas (supervisor+): un asesor
no debería ver el tablero completo del call center.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import requiere
from app.core.database import get_session
from app.models import AiCallUsage, CallLog, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Destinos internos de FreeSWITCH que no son un número real (ver calls.py).
_INTERNAL = ("x", "go")

# 0=domingo ... 6=sábado en extract('dow'), igual que JS getDay().
_SEMANA = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"]


@router.get("/call-center")
async def call_center_dashboard(
    days: int = Query(default=30, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
    _usuario: User = Depends(requiere(permissions.LLAMADAS_VER_TODAS)),
):
    desde = datetime.utcnow() - timedelta(days=days)

    # ---- Resumen / KPIs ---------------------------------------------------
    estado_rows = (
        await session.execute(
            select(CallLog.status, func.count(CallLog.id))
            .where(CallLog.started_at >= desde)
            .group_by(CallLog.status)
        )
    ).all()
    por_estado = {s: c for s, c in estado_rows}

    dir_rows = (
        await session.execute(
            select(CallLog.direction, func.count(CallLog.id))
            .where(CallLog.started_at >= desde)
            .group_by(CallLog.direction)
        )
    ).all()
    por_direccion = {d: c for d, c in dir_rows}

    talk_total = (
        await session.execute(
            select(func.coalesce(func.sum(CallLog.billsec), 0)).where(
                CallLog.started_at >= desde, CallLog.status == "answered"
            )
        )
    ).scalar() or 0
    avg_talk = (
        await session.execute(
            select(func.coalesce(func.avg(CallLog.billsec), 0)).where(
                CallLog.started_at >= desde, CallLog.status == "answered"
            )
        )
    ).scalar() or 0
    avg_wait = (
        await session.execute(
            select(
                func.coalesce(
                    func.avg(extract("epoch", CallLog.answered_at - CallLog.started_at)), 0
                )
            ).where(CallLog.started_at >= desde, CallLog.status == "answered")
        )
    ).scalar() or 0
    longest = (
        await session.execute(
            select(func.coalesce(func.max(CallLog.billsec), 0)).where(
                CallLog.started_at >= desde, CallLog.status == "answered"
            )
        )
    ).scalar() or 0

    total = sum(por_estado.values())
    answered = por_estado.get("answered", 0)

    resumen = {
        "total": total,
        "answered": answered,
        "no_answer": por_estado.get("no_answer", 0),
        "busy": por_estado.get("busy", 0),
        "failed": por_estado.get("failed", 0),
        "rejected": por_estado.get("rejected", 0),
        "cancelled": por_estado.get("cancelled", 0),
        "inbound": por_direccion.get("inbound", 0),
        "outbound": por_direccion.get("outbound", 0),
        "talk_seconds": talk_total,
        "avg_talk_seconds": round(float(avg_talk), 1),
        "avg_wait_seconds": round(float(avg_wait), 1),
        "longest_seconds": longest,
        "answer_rate": round(100 * answered / total, 1) if total else 0,
    }

    # ---- Serie por día (con huecos rellenados con cero) --------------------
    dia = func.to_char(CallLog.started_at, "YYYY-MM-DD").label("dia")
    answered_expr = func.sum(case((CallLog.status == "answered", 1), else_=0))
    dia_rows = (
        await session.execute(
            select(
                dia,
                func.count(CallLog.id).label("total"),
                answered_expr.label("answered"),
                func.coalesce(func.sum(CallLog.billsec), 0).label("talk"),
            )
            .where(CallLog.started_at >= desde)
            .group_by(dia)
            .order_by(dia)
        )
    ).all()
    por_dia_map = {r.dia: r for r in dia_rows}
    por_dia = []
    for i in range(days):
        fecha = (desde + timedelta(days=i)).strftime("%Y-%m-%d")
        r = por_dia_map.get(fecha)
        por_dia.append(
            {
                "dia": fecha,
                "total": r.total if r else 0,
                "answered": r.answered if r else 0,
                "talk": r.talk if r else 0,
            }
        )

    # ---- Por hora del día (0-23) ------------------------------------------
    hora = extract("hour", CallLog.started_at).label("hora")
    hora_rows = (
        await session.execute(
            select(hora, func.count(CallLog.id).label("total"), answered_expr.label("answered"))
            .where(CallLog.started_at >= desde)
            .group_by(hora)
            .order_by(hora)
        )
    ).all()
    por_hora_map = {int(r.hora): r for r in hora_rows}
    por_hora = [
        {"hora": h, "total": (por_hora_map.get(h).total if por_hora_map.get(h) else 0),
         "answered": (por_hora_map.get(h).answered if por_hora_map.get(h) else 0)}
        for h in range(24)
    ]

    # ---- Por día de la semana (0=domingo) ---------------------------------
    dow = extract("dow", CallLog.started_at).label("dow")
    dow_rows = (
        await session.execute(
            select(dow, func.count(CallLog.id).label("total"), answered_expr.label("answered"))
            .where(CallLog.started_at >= desde)
            .group_by(dow)
            .order_by(dow)
        )
    ).all()
    por_semana_map = {int(r.dow): r for r in dow_rows}
    por_semana = [
        {"dow": d, "label": _SEMANA[d], "total": (por_semana_map.get(d).total if por_semana_map.get(d) else 0),
         "answered": (por_semana_map.get(d).answered if por_semana_map.get(d) else 0)}
        for d in range(7)
    ]

    # ---- Top orígenes y destinos ------------------------------------------
    top_destinos_rows = (
        await session.execute(
            select(
                CallLog.callee_number,
                func.count(CallLog.id).label("total"),
                func.coalesce(func.sum(CallLog.billsec), 0).label("talk"),
            )
            .where(
                CallLog.started_at >= desde,
                CallLog.callee_number.is_not(None),
                CallLog.callee_number.not_in(_INTERNAL),
                CallLog.callee_number != "",
            )
            .group_by(CallLog.callee_number)
            .order_by(func.count(CallLog.id).desc())
            .limit(8)
        )
    ).all()
    top_destinos = [
        {"numero": r.callee_number, "total": r.total, "talk": r.talk} for r in top_destinos_rows
    ]

    top_origenes_rows = (
        await session.execute(
            select(CallLog.caller_number, func.count(CallLog.id).label("total"))
            .where(
                CallLog.started_at >= desde,
                CallLog.caller_number.is_not(None),
                CallLog.caller_number != "",
            )
            .group_by(CallLog.caller_number)
            .order_by(func.count(CallLog.id).desc())
            .limit(8)
        )
    ).all()
    top_origenes = [{"numero": r.caller_number, "total": r.total} for r in top_origenes_rows]

    # ---- Llamadas más largas ----------------------------------------------
    largas_rows = (
        await session.execute(
            select(CallLog.callee_number, CallLog.caller_number, CallLog.billsec, CallLog.started_at)
            .where(CallLog.started_at >= desde, CallLog.status == "answered")
            .order_by(CallLog.billsec.desc())
            .limit(5)
        )
    ).all()
    llamadas_largas = [
        {
            "callee": r.callee_number,
            "caller": r.caller_number,
            "billsec": r.billsec,
            "started_at": r.started_at,
        }
        for r in largas_rows
    ]

    # ---- Uso IA (voizbot) -------------------------------------------------
    ia_total = (
        await session.execute(select(func.count(AiCallUsage.id)).where(AiCallUsage.started_at >= desde))
    ).scalar() or 0
    ia_resolved = (
        await session.execute(
            select(func.count(AiCallUsage.id)).where(AiCallUsage.started_at >= desde, AiCallUsage.resolved.is_(True))
        )
    ).scalar() or 0
    ia_turns_avg = (
        await session.execute(
            select(func.coalesce(func.avg(AiCallUsage.turns), 0)).where(AiCallUsage.started_at >= desde)
        )
    ).scalar() or 0
    ia_outcomes_rows = (
        await session.execute(
            select(AiCallUsage.outcome, func.count(AiCallUsage.id))
            .where(AiCallUsage.started_at >= desde)
            .group_by(AiCallUsage.outcome)
            .order_by(func.count(AiCallUsage.id).desc())
        )
    ).all()
    ia = {
        "total": ia_total,
        "resolved": ia_resolved,
        "turns_avg": round(float(ia_turns_avg), 1),
        "resolution_rate": round(100 * ia_resolved / ia_total, 1) if ia_total else 0,
        "outcomes": [{"outcome": o, "count": c} for o, c in ia_outcomes_rows],
    }

    return {
        "desde": desde.isoformat(),
        "dias": days,
        "resumen": resumen,
        "por_dia": por_dia,
        "por_hora": por_hora,
        "por_semana": por_semana,
        "por_estado": [{"status": s, "count": c} for s, c in sorted(por_estado.items(), key=lambda x: -x[1])],
        "top_destinos": top_destinos,
        "top_origenes": top_origenes,
        "llamadas_largas": llamadas_largas,
        "ia": ia,
    }
