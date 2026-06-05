"""
IMPORFACTORY Premium — Router Admin (alumnos, cursos, agendamientos, config).

Endpoints read-mostly que alimentan las páginas del sidebar que antes daban 404.
Los datos de alumnos/cursos/agenda viven en el ERP (grupo_impor) → get_db_erp.
El estado de integraciones cruza empresa_config (ERP) + variables de entorno.

Endpoints /api/imporfactory/admin/{empresa_id}/...
2026-06-05.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, get_db_erp
from core.security import get_current_user
from models.models import Usuario


router = APIRouter(prefix="/api/imporfactory/admin", tags=["imporfactory-admin"])


def _ensure_empresa_5(empresa_id: int):
    if empresa_id != 5:
        raise HTTPException(403, "Solo empresa_id=5 (IMPORFACTORY)")


# ────────────────────────────────────────
# ALUMNOS
# ────────────────────────────────────────
@router.get("/{empresa_id}/alumnos")
async def listar_alumnos(
    empresa_id: int,
    q: Optional[str] = None,
    solo_activos: bool = False,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db_erp),
    user: Usuario = Depends(get_current_user),
):
    """Lista alumnos de IMPORFACTORY (empresa_id=5) desde el ERP."""
    _ensure_empresa_5(empresa_id)
    where = "WHERE empresa_id = 5"
    params = {"limit": min(limit, 500), "offset": max(offset, 0)}
    if solo_activos:
        where += " AND activo = 1"
    if q:
        where += " AND (nombre LIKE :q OR email LIKE :q OR whatsapp LIKE :q)"
        params["q"] = f"%{q}%"

    total = (await db.execute(text(f"SELECT COUNT(*) FROM alumnos {where}"), params)).scalar()
    activos = (await db.execute(text("SELECT COUNT(*) FROM alumnos WHERE empresa_id=5 AND activo=1"))).scalar()

    rows = (await db.execute(text(f"""
        SELECT id, nombre, email, whatsapp, pais, ciudad, activo,
               monto_pagado_total, fecha_registro, ultimo_login, fase_actual,
               cuotas_monto_pendiente, origen_compra
        FROM alumnos
        {where}
        ORDER BY fecha_registro DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()

    alumno_ids = [r["id"] for r in rows]
    mem_map = {}
    if alumno_ids:
        ph = ",".join(f":a{i}" for i in range(len(alumno_ids)))
        ap = {f"a{i}": aid for i, aid in enumerate(alumno_ids)}
        mrows = (await db.execute(text(f"""
            SELECT alumno_id, GROUP_CONCAT(DISTINCT tipo) AS tipos
            FROM alumno_membresias
            WHERE alumno_id IN ({ph}) AND activa = 1
            GROUP BY alumno_id
        """), ap)).mappings().all()
        mem_map = {m["alumno_id"]: m["tipos"] for m in mrows}

    items = []
    for r in rows:
        d = dict(r)
        d["membresias"] = (mem_map.get(r["id"]) or "").split(",") if mem_map.get(r["id"]) else []
        items.append(d)

    return {"items": items, "total": int(total or 0), "activos": int(activos or 0),
            "limit": params["limit"], "offset": params["offset"]}


# ────────────────────────────────────────
# CURSOS
# ────────────────────────────────────────
@router.get("/{empresa_id}/cursos")
async def listar_cursos(
    empresa_id: int,
    db: AsyncSession = Depends(get_db_erp),
    user: Usuario = Depends(get_current_user),
):
    """Lista cursos desde el ERP."""
    _ensure_empresa_5(empresa_id)
    rows = (await db.execute(text("""
        SELECT id, slug, titulo, descripcion, imagen_url, instructor, paquete,
               total_lecciones, total_modulos, duracion_total_min, orden, activo
        FROM cursos
        ORDER BY orden ASC, id ASC
    """))).mappings().all()
    return {"items": [dict(r) for r in rows]}


# ────────────────────────────────────────
# AGENDAMIENTOS (agenda_citas)
# ────────────────────────────────────────
@router.get("/{empresa_id}/agendamientos")
async def listar_agendamientos(
    empresa_id: int,
    estado: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_erp),
    user: Usuario = Depends(get_current_user),
):
    """Lista citas agendadas desde el ERP (agenda_citas)."""
    _ensure_empresa_5(empresa_id)
    where = "WHERE 1=1"
    params = {"limit": min(limit, 500)}
    if estado:
        where += " AND estado = :est"
        params["est"] = estado
    try:
        rows = (await db.execute(text(f"""
            SELECT id, nombre, email, telefono, fecha_hora_inicio, fecha_hora_fin,
                   estado, zoom_join_url, utm_source, utm_campaign, created_at
            FROM agenda_citas
            {where}
            ORDER BY fecha_hora_inicio DESC
            LIMIT :limit
        """), params)).mappings().all()
        # stats por estado
        stats = (await db.execute(text("""
            SELECT estado, COUNT(*) AS n FROM agenda_citas GROUP BY estado
        """))).mappings().all()
        return {"items": [dict(r) for r in rows], "stats": [dict(s) for s in stats]}
    except Exception as e:
        return {"items": [], "stats": [], "warning": str(e)[:120]}


# ────────────────────────────────────────
# CONFIG / INTEGRACIONES — estado (sin exponer secretos)
# ────────────────────────────────────────
@router.get("/{empresa_id}/config-status")
async def config_status(
    empresa_id: int,
    db: AsyncSession = Depends(get_db_erp),
    user: Usuario = Depends(get_current_user),
):
    """Estado de integraciones: configurado o no (NUNCA devuelve el valor)."""
    _ensure_empresa_5(empresa_id)

    cfg = (await db.execute(text("""
        SELECT clave, LENGTH(valor) AS lvalor FROM empresa_config
        WHERE empresa_id = 5
    """))).mappings().all()
    has_cfg = {c["clave"]: bool(c["lvalor"] and c["lvalor"] > 3) for c in cfg}

    def _ok(clave_env, *claves_cfg):
        if clave_env and os.environ.get(clave_env):
            return True
        return any(has_cfg.get(k, False) for k in claves_cfg)

    integraciones = [
        {"key": "anthropic", "nombre": "Claude AI (Anthropic)", "icon": "🤖",
         "desc": "Generación de texto del blog", "ok": _ok("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")},
        {"key": "gemini", "nombre": "Gemini Image", "icon": "🎨",
         "desc": "Miniaturas del blog", "ok": _ok("GEMINI_API_KEY", "GEMINI_API_KEY")},
        {"key": "openai", "nombre": "OpenAI (DALL-E)", "icon": "🖼️",
         "desc": "Imágenes alternativas", "ok": _ok("OPENAI_API_KEY", "OPENAI_API_KEY")},
        {"key": "zoom", "nombre": "Zoom", "icon": "📹",
         "desc": "Clases en vivo", "ok": _ok(None, "ZOOM_REFRESH_TOKEN", "ZOOM_ACCESS_TOKEN")},
        {"key": "youtube", "nombre": "YouTube Data API", "icon": "▶️",
         "desc": "Sync de videos", "ok": _ok(None, "YOUTUBE_REFRESH_TOKEN")},
        {"key": "datil", "nombre": "Datil (Facturación SRI)", "icon": "🧾",
         "desc": "Facturas electrónicas", "ok": _ok(None, "DATIL_API_KEY")},
        {"key": "smtp", "nombre": "SMTP (Email)", "icon": "📧",
         "desc": "Envío de correos", "ok": _ok(None, "SMTP_HOST", "SMTP_USER")},
        {"key": "whatsapp", "nombre": "WhatsApp (wacli)", "icon": "💬",
         "desc": "Mensajería / recordatorios", "ok": True},
    ]
    return {"integraciones": integraciones,
            "total_ok": sum(1 for i in integraciones if i["ok"]),
            "total": len(integraciones)}
