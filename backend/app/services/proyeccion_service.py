"""
IMPORFACTORY Premium — Proyector de ventas.

Modelo (decidido con datos reales + Daniel, 2026-06-06):
  - El REPARTO por asesor sale del histórico real (share de monto_pagado_total):
    Adrian 41% · Eve 29% · Kathy 22% · Karito 5% · Diego 3%.
  - El TAMAÑO de la meta lo proyecta Daniel con la inversión en ads:
        meta_ventas_equipo = venta_organica + inversion_ads * ROAS   (ROAS 3x default)
        meta_asesor        = meta_ventas_equipo * share_asesor
        meta_cobranza       = meta_ventas * pct_cobranza/100
        alumnos_proyectados = meta_ventas_equipo / ticket_promedio   (ticket real $486)

Config en tabla ventas_proyeccion (singleton id=1). Metas resultantes se persisten
en cobranza_metas (meta_ventas + meta_mensual=meta_cobranza) para el tablero TV.

2026-06-06 Sprint 36.2.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_config(db: AsyncSession) -> dict:
    row = (await db.execute(text("""
        SELECT inversion_ads, roas, venta_organica, ticket_promedio, pct_cobranza
        FROM ventas_proyeccion WHERE id = 1
    """))).mappings().first()
    if not row:
        return {"inversion_ads": 5000.0, "roas": 3.0, "venta_organica": 5000.0,
                "ticket_promedio": 486.0, "pct_cobranza": 100.0}
    return {k: float(v) for k, v in dict(row).items()}


async def save_config(db: AsyncSession, inversion_ads: float, roas: float,
                      venta_organica: float, ticket_promedio: float, pct_cobranza: float) -> None:
    await db.execute(text("""
        INSERT INTO ventas_proyeccion (id, inversion_ads, roas, venta_organica, ticket_promedio, pct_cobranza)
        VALUES (1, :a, :r, :o, :t, :c)
        ON DUPLICATE KEY UPDATE
            inversion_ads = VALUES(inversion_ads), roas = VALUES(roas),
            venta_organica = VALUES(venta_organica), ticket_promedio = VALUES(ticket_promedio),
            pct_cobranza = VALUES(pct_cobranza)
    """), {"a": inversion_ads, "r": roas, "o": venta_organica, "t": ticket_promedio, "c": pct_cobranza})
    await db.commit()


async def compute(db: AsyncSession) -> dict:
    """Calcula la proyección completa (equipo + por asesor) SIN persistir."""
    cfg = await get_config(db)
    meta_ventas_eq = cfg["venta_organica"] + cfg["inversion_ads"] * cfg["roas"]
    meta_cobranza_eq = meta_ventas_eq * cfg["pct_cobranza"] / 100.0
    ticket = cfg["ticket_promedio"] or 486.0
    alumnos = round(meta_ventas_eq / ticket) if ticket else 0

    asesores = (await db.execute(text("""
        SELECT asesor, share_pct FROM cobranza_metas WHERE activo = 1 ORDER BY share_pct DESC
    """))).mappings().all()

    out = []
    for a in asesores:
        share = float(a["share_pct"] or 0)
        mv = round(meta_ventas_eq * share / 100.0, 2)
        out.append({
            "asesor": a["asesor"],
            "share_pct": share,
            "meta_ventas": mv,
            "meta_cobranza": round(mv * cfg["pct_cobranza"] / 100.0, 2),
            "alumnos": round(mv / ticket) if ticket else 0,
        })

    return {
        "config": cfg,
        "meta_ventas_equipo": round(meta_ventas_eq, 2),
        "meta_cobranza_equipo": round(meta_cobranza_eq, 2),
        "alumnos_proyectados": alumnos,
        "ventas_por_ads": round(cfg["inversion_ads"] * cfg["roas"], 2),
        "asesores": out,
    }


async def recalcular_y_guardar(db: AsyncSession) -> dict:
    """Calcula y PERSISTE las metas en cobranza_metas (meta_ventas + meta_mensual=cobranza)."""
    proy = await compute(db)
    for a in proy["asesores"]:
        await db.execute(text("""
            UPDATE cobranza_metas
            SET meta_ventas = :mv, meta_mensual = :mc
            WHERE asesor = :asesor
        """), {"mv": a["meta_ventas"], "mc": a["meta_cobranza"], "asesor": a["asesor"]})
    await db.commit()
    return proy
