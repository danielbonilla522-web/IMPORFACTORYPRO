"""API Reto Importador Rentable — público (sin auth).

POST /api/reto/registro → crea lead + genera folio + redirect URL del certificado.
GET /api/reto/lead/{folio} → obtiene datos para renderizar certificado.
"""
from __future__ import annotations

import os
import re
import secrets
import string
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db


router = APIRouter(prefix="/api/reto", tags=["reto-importador"])


# ─── Modelos ───

class RetoRegistroPayload(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=180)
    telefono: str = Field(..., min_length=6, max_length=40)
    pais_codigo: str = Field(default="+593", max_length=8)
    email: EmailStr
    dedicacion: str = Field(..., max_length=80)
    producto_interes: Optional[str] = Field(default=None, max_length=220)
    capital_disponible: str = Field(..., max_length=40)
    conoce_club: str = Field(..., max_length=40)

    @field_validator("nombre")
    @classmethod
    def _clean_nombre(cls, v: str) -> str:
        return " ".join(v.strip().split())[:180]

    @field_validator("telefono")
    @classmethod
    def _clean_tel(cls, v: str) -> str:
        return re.sub(r"\D", "", v)[:40]

    @field_validator("conoce_club")
    @classmethod
    def _valid_club(cls, v: str) -> str:
        valid = {"si_ya_conozco", "quiero_asesor", "quiero_ingresar", "no_interesa"}
        if v not in valid:
            raise ValueError("conoce_club invalido")
        return v



MESES_ES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]


def _fecha_es(dt) -> str:
    if not dt:
        return ""
    return f"{dt.day:02d} de {MESES_ES[dt.month - 1]} de {dt.year}"


def _gen_folio() -> str:
    """RIR-YYYY-XXXXXX (formato amigable)."""
    chars = string.ascii_uppercase + string.digits
    rnd = "".join(secrets.choice(chars) for _ in range(6))
    return f"RIR-{datetime.now().year}-{rnd}"


# ─── Endpoints ───

@router.post("/registro")
async def registro(
    payload: RetoRegistroPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Crea lead nuevo y devuelve folio + URL del certificado."""
    folio = _gen_folio()
    # Garantizar unicidad (retry hasta 3)
    for _ in range(3):
        existing = (await db.execute(
            text("SELECT 1 FROM leads_reto_importador WHERE folio = :f"),
            {"f": folio},
        )).first()
        if not existing:
            break
        folio = _gen_folio()

    ip = (request.headers.get("x-forwarded-for") or request.client.host or "").split(",")[0].strip()[:60]
    ua = (request.headers.get("user-agent") or "")[:400]

    res = await db.execute(text("""
        INSERT INTO leads_reto_importador
            (nombre, telefono, pais_codigo, email, dedicacion, producto_interes,
             capital_disponible, conoce_club, folio, ip, user_agent)
        VALUES
            (:nombre, :telefono, :pais, :email, :ded, :prod, :cap, :club, :folio, :ip, :ua)
    """), {
        "nombre": payload.nombre,
        "telefono": payload.telefono,
        "pais": payload.pais_codigo,
        "email": str(payload.email),
        "ded": payload.dedicacion,
        "prod": (payload.producto_interes or "").strip()[:220] or None,
        "cap": payload.capital_disponible,
        "club": payload.conoce_club,
        "folio": folio,
        "ip": ip, "ua": ua,
    })
    await db.commit()

    return {
        "ok": True,
        "folio": folio,
        "lead_id": res.lastrowid,
        "certificado_url": f"/certificado/{folio}",
    }


@router.get("/lead/{folio}")
async def get_lead_by_folio(
    folio: str,
    db: AsyncSession = Depends(get_db),
):
    """Devuelve datos del lead para renderizar certificado (público — usa folio como token)."""
    row = (await db.execute(text("""
        SELECT id, nombre, email, folio, edicion_reto, fecha_emision
        FROM leads_reto_importador WHERE folio = :f
    """), {"f": folio})).mappings().first()
    if not row:
        raise HTTPException(404, "Folio no encontrado")
    return {
        "folio": row["folio"],
        "nombre": row["nombre"],
        "email": row["email"],
        "edicion_reto": row["edicion_reto"],
        "fecha_emision": row["fecha_emision"].isoformat() if row["fecha_emision"] else None,
        "fecha_humana": _fecha_es(row["fecha_emision"]),
    }
