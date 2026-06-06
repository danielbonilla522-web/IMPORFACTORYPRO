"""
IMPORFACTORY Premium — Tablero TV de Cobranzas/Ventas + Proyector.

- Tablero TV (PÚBLICO con clave ?key=): ranking de asesores con VENDIDO y COBRADO
  vs sus metas (la tele lo abre sin login).
- Proyector (auth JWT): configurar inversión en ads / ROAS y recalcular metas
  fundamentadas en el share histórico real.

2026-06-06 Sprint 36 / 36.2.
"""
from __future__ import annotations

import os
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.models import Usuario
from services.carterachat_service import get_ranking_cobranzas
from services import proyeccion_service as proy


router = APIRouter(prefix="/api/cobranzas", tags=["cobranzas-tv"])

_DIAS_HABILES_MES = 22


def check_tv_key(key: str):
    expected = os.environ.get("TV_COBRANZAS_KEY", "")
    if not expected or key != expected:
        raise HTTPException(403, "Clave de tablero inválida")


def _periodo_rango(periodo: str) -> tuple[str, str]:
    hoy = date.today()
    if periodo == "hoy":
        return hoy.isoformat(), hoy.isoformat()
    return hoy.replace(day=1).isoformat(), hoy.isoformat()


def _pct(real: float, meta: float):
    return round(real / meta * 100, 1) if meta and meta > 0 else None


# ════════════════════════════════════════════════════════════
# TABLERO TV (público con key)
# ════════════════════════════════════════════════════════════
@router.get("/tv/ranking")
async def tv_ranking(
    periodo: str = "mes",
    key: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    check_tv_key(key)
    periodo = "hoy" if periodo == "hoy" else "mes"
    desde, hasta = _periodo_rango(periodo)
    factor = 1.0 if periodo == "mes" else 1.0 / _DIAS_HABILES_MES

    ranking = await get_ranking_cobranzas(desde, hasta)
    items = list(ranking.get("items") or [])

    # Metas por asesor (ventas + cobranza) desde cobranza_metas
    metas = {}
    try:
        rows = (await db.execute(text("""
            SELECT asesor, meta_ventas, meta_mensual AS meta_cobranza
            FROM cobranza_metas WHERE activo = 1
        """))).mappings().all()
        metas = {r["asesor"].strip().lower(): r for r in rows}
    except Exception:
        metas = {}

    items.sort(key=lambda x: x.get("total_vendido", 0), reverse=True)

    asesores = []
    tot_vendido = tot_cobrado = tot_vencido = 0.0
    tot_ventas = tot_pagos = 0
    meta_v_eq = meta_c_eq = 0.0
    for i, it in enumerate(items):
        m = metas.get(str(it.get("asesor", "")).strip().lower())
        meta_v = round(float(m["meta_ventas"]) * factor, 2) if m else 0.0
        meta_c = round(float(m["meta_cobranza"]) * factor, 2) if m else 0.0
        vendido = float(it.get("total_vendido") or 0)
        cobrado = float(it.get("total_cobrado") or 0)
        tot_vendido += vendido
        tot_cobrado += cobrado
        tot_vencido += float(it.get("monto_vencido") or 0)
        tot_ventas += int(it.get("num_ventas") or 0)
        tot_pagos += int(it.get("num_pagos") or 0)
        meta_v_eq += meta_v
        meta_c_eq += meta_c
        asesores.append({
            "rank": i + 1,
            "asesor": it.get("asesor"),
            "vendido": round(vendido, 2),
            "meta_ventas": meta_v,
            "pct_ventas": _pct(vendido, meta_v),
            "num_ventas": int(it.get("num_ventas") or 0),
            "cobrado": round(cobrado, 2),
            "meta_cobranza": meta_c,
            "pct_cobranza": _pct(cobrado, meta_c),
            "num_pagos": int(it.get("num_pagos") or 0),
            "monto_vencido": round(float(it.get("monto_vencido") or 0), 2),
            "num_clientes": int(it.get("num_clientes") or 0),
        })

    return {
        "periodo": periodo,
        "desde": desde,
        "hasta": hasta,
        "source": ranking.get("source"),
        "api_error": ranking.get("api_error"),
        "total_vendido": round(tot_vendido, 2),
        "total_cobrado": round(tot_cobrado, 2),
        "meta_ventas_equipo": round(meta_v_eq, 2),
        "meta_cobranza_equipo": round(meta_c_eq, 2),
        "total_vencido": round(tot_vencido, 2),
        "total_ventas": tot_ventas,
        "total_pagos": tot_pagos,
        "asesores": asesores,
    }


# ════════════════════════════════════════════════════════════
# PROYECTOR (auth JWT)
# ════════════════════════════════════════════════════════════
class ProyeccionPayload(BaseModel):
    inversion_ads: float
    roas: float = 3.0
    venta_organica: float = 0.0
    ticket_promedio: float = 486.0
    pct_cobranza: float = 100.0


@router.get("/proyeccion")
async def get_proyeccion(
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Proyección actual (config + metas calculadas por asesor). NO persiste."""
    return await proy.compute(db)


@router.put("/proyeccion")
async def put_proyeccion(
    payload: ProyeccionPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Guarda la config del proyector y RECALCULA las metas (persiste en cobranza_metas)."""
    if payload.inversion_ads < 0 or payload.roas < 0 or payload.ticket_promedio <= 0:
        raise HTTPException(400, "Valores inválidos")
    await proy.save_config(db, payload.inversion_ads, payload.roas,
                           payload.venta_organica, payload.ticket_promedio, payload.pct_cobranza)
    proyeccion = await proy.recalcular_y_guardar(db)
    return {"ok": True, "proyeccion": proyeccion}
