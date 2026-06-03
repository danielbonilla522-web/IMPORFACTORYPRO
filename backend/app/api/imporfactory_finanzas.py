"""
IMPORFACTORY Premium — Router de Finanzas / KPIs ejecutivos.

Endpoints bajo /api/imporfactory/finanzas/{empresa_id}/...

Diseño: el endpoint /dashboard lee snapshot cacheado (rápido, <100ms).
Si no hay snapshot del día, calcula EN VIVO una vez y lo persiste.
Cron /home/ubuntu/sistema/backend/app/scripts/cron_finanzas_snapshot.py
refresca cada 6h.

2026-05-27 Sprint 3.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.models import Usuario

from services.imporfactory_finanzas_service import (
    compute_snapshot,
    upsert_snapshot,
    get_latest_snapshot,
    get_mrr_historico,
)


router = APIRouter(prefix="/api/imporfactory/finanzas", tags=["imporfactory-finanzas"])


def _ensure_empresa_5(empresa_id: int):
    """IMPORFACTORY Premium es exclusivamente empresa_id=5."""
    if empresa_id != 5:
        raise HTTPException(403, "Solo empresa_id=5 (IMPORFACTORY) está habilitada")


@router.get("/{empresa_id}/dashboard")
async def dashboard(
    empresa_id: int,
    forzar: bool = False,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Devuelve KPIs ejecutivos. Si no hay snapshot del día (o forzar=True), recalcula."""
    _ensure_empresa_5(empresa_id)

    snap = await get_latest_snapshot(db, empresa_id)
    needs_refresh = (
        forzar
        or snap is None
        or (snap.get("fecha") != date.today())
    )

    if needs_refresh:
        fresh = await compute_snapshot(db, empresa_id)
        await upsert_snapshot(db, fresh)
        snap = await get_latest_snapshot(db, empresa_id)

    if not snap:
        raise HTTPException(500, "No se pudo calcular el snapshot")

    # Serializar fechas/decimals
    def _conv(v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        if hasattr(v, "__float__") and not isinstance(v, (int, bool)):
            try:
                return float(v)
            except Exception:
                return str(v)
        return v

    return {k: _conv(v) for k, v in snap.items()}


@router.get("/{empresa_id}/mrr-historico")
async def mrr_historico(
    empresa_id: int,
    dias: int = 90,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Serie temporal de MRR para gráfico line chart."""
    _ensure_empresa_5(empresa_id)
    if dias < 7 or dias > 365:
        raise HTTPException(400, "dias debe estar entre 7 y 365")

    rows = await get_mrr_historico(db, empresa_id, dias)
    return {
        "dias": dias,
        "series": [
            {"fecha": r["fecha"].isoformat() if r.get("fecha") else None,
             "mrr": float(r["mrr"]) if r.get("mrr") else 0,
             "alumnos_activos": int(r.get("alumnos_activos") or 0)}
            for r in rows
        ],
    }


@router.post("/{empresa_id}/snapshot-now")
async def snapshot_now(
    empresa_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Fuerza recálculo de KPIs (uso admin / debug)."""
    _ensure_empresa_5(empresa_id)
    snap = await compute_snapshot(db, empresa_id)
    snap_id = await upsert_snapshot(db, snap)
    return {"ok": True, "snapshot_id": snap_id, "fecha": snap["fecha"].isoformat()}


@router.get("/{empresa_id}/cuentas-por-cobrar")
async def cuentas_por_cobrar(
    empresa_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Lista alumnos con pagos pendientes (cuotas_monto_pendiente > 0)."""
    _ensure_empresa_5(empresa_id)

    from sqlalchemy import text
    try:
        rows = (await db.execute(text("""
            SELECT id, nombre, email, whatsapp, cuotas_monto_pendiente
            FROM alumnos
            WHERE empresa_id = :emp AND activo = 1
              AND cuotas_monto_pendiente IS NOT NULL
              AND cuotas_monto_pendiente > 0
            ORDER BY cuotas_monto_pendiente DESC
            LIMIT 100
        """), {"emp": empresa_id})).mappings().all()
        return {"items": [dict(r) for r in rows]}
    except Exception as e:
        # Tabla puede no tener la columna; devolvemos vacío sin romper UI
        return {"items": [], "warning": str(e)}


@router.get("/{empresa_id}/membresias-resumen")
async def membresias_resumen(
    empresa_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Distribución actual de membresías por tipo."""
    _ensure_empresa_5(empresa_id)

    from sqlalchemy import text
    rows = (await db.execute(text("""
        SELECT tipo, COUNT(*) AS n,
               SUM(CASE WHEN fecha_vencimiento IS NULL OR fecha_vencimiento > NOW() THEN 1 ELSE 0 END) AS vigentes,
               SUM(CASE WHEN fecha_vencimiento IS NOT NULL AND fecha_vencimiento <= NOW() THEN 1 ELSE 0 END) AS vencidas
        FROM alumno_membresias
        WHERE activa = 1
        GROUP BY tipo
        ORDER BY n DESC
    """))).mappings().all()

    return {
        "items": [
            {"tipo": r["tipo"], "n": int(r["n"]),
             "vigentes": int(r["vigentes"] or 0),
             "vencidas": int(r["vencidas"] or 0)}
            for r in rows
        ]
    }
