"""
IMPORFACTORY Premium — Router del Tablero TV de Cobranzas (leaderboard asesores).

Endpoint PÚBLICO protegido por clave (?key=) — la tele de la oficina lo abre sin login.
Lee el ranking de $ cobrado desde Carterachat (con fallback mock) y lo cruza con las
metas configurables (tabla cobranza_metas en la BD propia).

GET /api/cobranzas/tv/ranking?periodo=hoy|mes&key=XXX
2026-06-06 Sprint 36.
"""
from __future__ import annotations

import os
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.carterachat_service import get_ranking_cobranzas


router = APIRouter(prefix="/api/cobranzas", tags=["cobranzas-tv"])


def check_tv_key(key: str):
    """Valida la clave secreta de la TV (TV_COBRANZAS_KEY en .env)."""
    expected = os.environ.get("TV_COBRANZAS_KEY", "")
    if not expected or key != expected:
        raise HTTPException(403, "Clave de tablero inválida")


def _periodo_rango(periodo: str) -> tuple[str, str]:
    hoy = date.today()
    if periodo == "hoy":
        return hoy.isoformat(), hoy.isoformat()
    # mes (default): del 1ro a hoy
    return hoy.replace(day=1).isoformat(), hoy.isoformat()


# ~días hábiles para prorratear la meta mensual cuando el periodo es "hoy"
_DIAS_HABILES_MES = 22


@router.get("/tv/ranking")
async def tv_ranking(
    periodo: str = "mes",
    key: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    check_tv_key(key)
    periodo = "hoy" if periodo == "hoy" else "mes"
    desde, hasta = _periodo_rango(periodo)

    ranking = await get_ranking_cobranzas(desde, hasta)
    items = list(ranking.get("items") or [])

    # Metas configurables (BD propia)
    metas = {}
    try:
        rows = (await db.execute(text(
            "SELECT asesor, meta_mensual FROM cobranza_metas WHERE activo = 1"
        ))).mappings().all()
        metas = {r["asesor"].strip().lower(): float(r["meta_mensual"]) for r in rows}
    except Exception:
        metas = {}

    items.sort(key=lambda x: x.get("total_cobrado", 0), reverse=True)

    asesores = []
    total_equipo = 0.0
    total_pagos = 0
    total_vencido = 0.0
    for i, it in enumerate(items):
        meta_mensual = metas.get(str(it.get("asesor", "")).strip().lower(), 0.0)
        meta_periodo = meta_mensual if periodo == "mes" else round(meta_mensual / _DIAS_HABILES_MES, 2)
        cobrado = float(it.get("total_cobrado") or 0)
        pct = round(cobrado / meta_periodo * 100, 1) if meta_periodo > 0 else None
        total_equipo += cobrado
        total_pagos += int(it.get("num_pagos") or 0)
        total_vencido += float(it.get("monto_vencido") or 0)
        asesores.append({
            "rank": i + 1,
            "asesor": it.get("asesor"),
            "total_cobrado": round(cobrado, 2),
            "num_pagos": int(it.get("num_pagos") or 0),
            "monto_vencido": round(float(it.get("monto_vencido") or 0), 2),
            "num_clientes": int(it.get("num_clientes") or 0),
            "meta": meta_periodo,
            "pct_meta": pct,
        })

    meta_equipo = round(sum(metas.values()) if periodo == "mes"
                        else sum(metas.values()) / _DIAS_HABILES_MES, 2)

    return {
        "periodo": periodo,
        "desde": desde,
        "hasta": hasta,
        "source": ranking.get("source"),
        "api_error": ranking.get("api_error"),
        "total_equipo": round(total_equipo, 2),
        "meta_equipo": meta_equipo,
        "total_pagos": total_pagos,
        "total_vencido": round(total_vencido, 2),
        "asesores": asesores,
    }
