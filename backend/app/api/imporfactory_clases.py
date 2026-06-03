"""
IMPORFACTORY Premium — Router de clases en vivo.

Endpoints /api/imporfactory/clases/{empresa_id}/...
2026-05-27 Sprint 4.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.models import Usuario

from services.imporfactory_clases_service import (
    crear_clase,
    listar_clases,
    get_clase_detalle,
    inscribir_masivo,
    schedule_reminders_for_clase,
    enqueue_pending_reminders,
)


router = APIRouter(prefix="/api/imporfactory/clases", tags=["imporfactory-clases"])


def _ensure_empresa_5(empresa_id: int):
    if empresa_id != 5:
        raise HTTPException(403, "Solo empresa_id=5 (IMPORFACTORY)")


class CrearClasePayload(BaseModel):
    titulo: str
    descripcion: Optional[str] = None
    instructor: Optional[str] = "Daniel Bonilla"
    fecha_inicio: datetime
    duracion_min: int = 60
    zoom_meeting_id: Optional[str] = None
    zoom_join_url: Optional[str] = None
    zoom_password: Optional[str] = None
    max_asistentes: int = 1000
    dirigida_a: list[str] = []
    slug: Optional[str] = None
    notas_internas: Optional[str] = None


class InscribirMasivoPayload(BaseModel):
    filtro_membresia: list[str]


@router.get("/{empresa_id}")
async def listar(
    empresa_id: int,
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    items = await listar_clases(db, estado=estado)
    return {"items": items}


@router.post("/{empresa_id}")
async def crear(
    empresa_id: int,
    payload: CrearClasePayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    clase_id = await crear_clase(db, payload.dict(), created_by=user.id)
    return {"ok": True, "clase_id": clase_id}


@router.get("/{empresa_id}/{clase_id}")
async def detalle(
    empresa_id: int,
    clase_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    d = await get_clase_detalle(db, clase_id)
    if not d:
        raise HTTPException(404, "Clase no encontrada")
    return d


@router.put("/{empresa_id}/{clase_id}")
async def editar(
    empresa_id: int,
    clase_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    # Permitimos editar campos seguros nada más
    safe_fields = {
        "titulo", "descripcion", "instructor", "fecha_inicio", "duracion_min",
        "zoom_meeting_id", "zoom_join_url", "zoom_password",
        "max_asistentes", "estado", "grabacion_url", "notas_internas",
    }
    updates = {k: v for k, v in payload.items() if k in safe_fields}
    if not updates:
        raise HTTPException(400, "Nada que actualizar")
    set_clauses = ", ".join([f"{k} = :{k}" for k in updates])
    updates["_id"] = clase_id
    await db.execute(text(f"UPDATE clases_vivas SET {set_clauses} WHERE id = :_id"), updates)
    await db.commit()

    # Si cambió la fecha, reprogramar recordatorios
    if "fecha_inicio" in updates:
        await db.execute(text("DELETE FROM clase_recordatorios WHERE clase_id = :id"), {"id": clase_id})
        await db.commit()
        await schedule_reminders_for_clase(db, clase_id)

    return {"ok": True}


@router.post("/{empresa_id}/{clase_id}/inscribir-masivo")
async def inscribir_masivo_endpoint(
    empresa_id: int,
    clase_id: int,
    payload: InscribirMasivoPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    n = await inscribir_masivo(db, clase_id, payload.filtro_membresia)
    return {"ok": True, "inscritos_nuevos": n}


@router.post("/{empresa_id}/{clase_id}/recordatorios/programar")
async def reprogramar_recordatorios(
    empresa_id: int,
    clase_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    n = await schedule_reminders_for_clase(db, clase_id)
    return {"ok": True, "recordatorios_creados": n}


@router.post("/{empresa_id}/recordatorios/encolar-ahora")
async def encolar_pendientes(
    empresa_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Fuerza drenado del cron: encola TODOS los recordatorios pendientes que ya cumplieron tiempo."""
    _ensure_empresa_5(empresa_id)
    n = await enqueue_pending_reminders(db, lookahead_min=1)
    return {"ok": True, "encolados": n}


@router.delete("/{empresa_id}/{clase_id}")
async def cancelar_clase(
    empresa_id: int,
    clase_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    await db.execute(text("UPDATE clases_vivas SET estado='cancelada' WHERE id = :id"), {"id": clase_id})
    # Limpiar recordatorios pendientes
    await db.execute(text("""
        UPDATE clase_recordatorios SET estado='no_aplica', error_msg='clase cancelada'
        WHERE clase_id = :id AND estado='pendiente'
    """), {"id": clase_id})
    await db.commit()
    return {"ok": True}
