"""
IMPORFACTORY Premium — Router Mensajeria (cola WA + templates + broadcast).

Endpoints /api/imporfactory/wa/{empresa_id}/...
2026-05-27 Sprint 7.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.models import Usuario

from services.imporfactory_clases_service import normalize_phone


router = APIRouter(prefix="/api/imporfactory/wa", tags=["imporfactory-mensajeria"])


def _ensure_empresa_5(empresa_id: int):
    if empresa_id != 5:
        raise HTTPException(403, "Solo empresa_id=5 (IMPORFACTORY)")


class BroadcastPayload(BaseModel):
    mensaje: str
    filtro_membresia: list[str] = []
    dry_run: bool = True
    max_per_minute: int = 30


@router.get("/{empresa_id}/cola")
async def listar_cola(
    empresa_id: int,
    estado: Optional[str] = None,
    trigger_origen: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    where = "WHERE empresa_id = 5"
    params = {"limit": limit}
    if estado:
        where += " AND estado = :est"
        params["est"] = estado
    if trigger_origen:
        where += " AND trigger_origen = :tor"
        params["tor"] = trigger_origen

    rows = (await db.execute(text(f"""
        SELECT id, alumno_id, telefono, estado, intentos, last_error, scheduled_at,
               sent_at, created_at, batch_id, trigger_origen,
               SUBSTRING(mensaje, 1, 120) AS mensaje_preview
        FROM whatsapp_queue
        {where}
        ORDER BY created_at DESC LIMIT :limit
    """), params)).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.get("/{empresa_id}/cola/stats")
async def cola_stats(
    empresa_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    rows = (await db.execute(text("""
        SELECT estado, COUNT(*) AS n FROM whatsapp_queue
        WHERE empresa_id = 5 AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        GROUP BY estado
    """))).mappings().all()

    triggers = (await db.execute(text("""
        SELECT COALESCE(trigger_origen, 'manual') AS trigger_origen,
               COUNT(*) AS n,
               SUM(CASE WHEN estado='ENVIADO' THEN 1 ELSE 0 END) AS enviados
        FROM whatsapp_queue
        WHERE empresa_id = 5 AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        GROUP BY trigger_origen
        ORDER BY n DESC
    """))).mappings().all()

    return {
        "estados_7d": [dict(r) for r in rows],
        "triggers_30d": [dict(r) for r in triggers],
    }


@router.post("/{empresa_id}/cola/{queue_id}/reintentar")
async def reintentar(
    empresa_id: int,
    queue_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    res = await db.execute(text("""
        UPDATE whatsapp_queue
        SET estado='PENDIENTE', intentos=0, last_error=NULL, scheduled_at=NOW()
        WHERE id = :id AND empresa_id = 5
    """), {"id": queue_id})
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Mensaje no encontrado")
    return {"ok": True}


@router.post("/{empresa_id}/cola/{queue_id}/cancelar")
async def cancelar(
    empresa_id: int,
    queue_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    res = await db.execute(text("""
        UPDATE whatsapp_queue SET estado='FALLIDO', last_error='cancelado_manualmente'
        WHERE id = :id AND empresa_id = 5 AND estado IN ('PENDIENTE','ENVIANDO')
    """), {"id": queue_id})
    await db.commit()
    return {"ok": True, "actualizados": res.rowcount}


@router.post("/{empresa_id}/broadcast")
async def broadcast(
    empresa_id: int,
    payload: BroadcastPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Encola mensaje masivo a segmento de alumnos con rate-limit.

    Soporta {nombre} placeholder en el mensaje. dry_run=True solo cuenta destinatarios.
    """
    _ensure_empresa_5(empresa_id)

    # Identificar destinatarios
    if payload.filtro_membresia:
        placeholders = ",".join([f":t{i}" for i in range(len(payload.filtro_membresia))])
        params = {f"t{i}": t for i, t in enumerate(payload.filtro_membresia)}
        rows = (await db.execute(text(f"""
            SELECT DISTINCT a.id, a.nombre, a.whatsapp
            FROM alumnos a
            JOIN alumno_membresias am ON am.alumno_id = a.id
            WHERE a.empresa_id = 5 AND a.activo = 1 AND a.whatsapp IS NOT NULL
              AND am.activa = 1 AND am.tipo IN ({placeholders})
        """), params)).mappings().all()
    else:
        rows = (await db.execute(text("""
            SELECT id, nombre, whatsapp FROM alumnos
            WHERE empresa_id = 5 AND activo = 1 AND whatsapp IS NOT NULL
        """))).mappings().all()

    # Filtrar tel válidos
    destinatarios = []
    for r in rows:
        tel = normalize_phone(r["whatsapp"])
        if tel:
            destinatarios.append({"id": r["id"], "nombre": r["nombre"], "telefono": tel})

    if payload.dry_run:
        return {
            "dry_run": True,
            "total_destinatarios": len(destinatarios),
            "primeros_5": destinatarios[:5],
            "tiempo_estimado_min": round(len(destinatarios) / max(payload.max_per_minute, 1), 1),
        }

    # Encolar con offset progresivo para respetar rate limit
    batch_id = "bc-" + uuid.uuid4().hex[:12]
    offset_sec = 60.0 / max(payload.max_per_minute, 1)
    encolados = 0
    for i, d in enumerate(destinatarios):
        sched = datetime.utcnow() + timedelta(seconds=i * offset_sec)
        mensaje_personalizado = payload.mensaje.replace("{nombre}", (d["nombre"] or "amigo").split(" ")[0])
        jid = d["telefono"] + "@s.whatsapp.net"
        await db.execute(text("""
            INSERT INTO whatsapp_queue
                (empresa_id, alumno_id, telefono, jid, mensaje, wacli_store,
                 scheduled_at, batch_id, trigger_origen)
            VALUES
                (5, :aid, :tel, :jid, :msg, '/home/ubuntu/.wacli-imporfactory',
                 :sch, :batch, 'broadcast_manual')
        """), {
            "aid": d["id"], "tel": d["telefono"], "jid": jid, "msg": mensaje_personalizado,
            "sch": sched, "batch": batch_id,
        })
        encolados += 1
    await db.commit()
    return {"ok": True, "batch_id": batch_id, "encolados": encolados,
            "tiempo_estimado_min": round(encolados / payload.max_per_minute, 1)}


@router.get("/{empresa_id}/costos-ai")
async def costos_ai_30d(
    empresa_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Resumen de costos AI últimos 30 días (Claude + DALL-E)."""
    _ensure_empresa_5(empresa_id)
    rows = (await db.execute(text("""
        SELECT modelo_usado, tipo,
               COUNT(*) AS n,
               SUM(costo_usd) AS total_usd,
               SUM(tokens_input) AS tokens_in,
               SUM(tokens_output) AS tokens_out
        FROM blog_generaciones_ai
        WHERE generado_en >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        GROUP BY modelo_usado, tipo
        ORDER BY total_usd DESC
    """))).mappings().all()
    total = sum(float(r.get("total_usd") or 0) for r in rows)
    return {"items": [dict(r) for r in rows], "total_30d_usd": round(total, 4)}
