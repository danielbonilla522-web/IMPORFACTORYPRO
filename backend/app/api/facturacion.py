"""API Facturación masiva — IMPORFACTORY Premium.

Endpoints:
- GET  /api/facturacion/empresas — lista empresas con Datil configurado
- POST /api/facturacion/borrador — crea factura en estado 'borrador'
- GET  /api/facturacion/borradores?empresa_id=4&estado=borrador — lista
- PUT  /api/facturacion/borrador/{id} — editar
- DELETE /api/facturacion/borrador/{id} — eliminar
- POST /api/facturacion/emitir-batch — emite N facturas seleccionadas

Sin auth (uso interno staff). En producción agregar Depends(get_current_user).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, get_db_erp
from services import datil
from services import datil_helper as dh


router = APIRouter(prefix="/api/facturacion", tags=["facturacion"])


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

# IMPORFACTORY exclusivamente — cada empresa tiene su propio sistema separado
EMPRESA_ID = 5
EMPRESA_INFO = {"nombre": "IMPORFACTORY", "ruc_display": "1722377726001"}


def _calc_totales(items_json: list[dict], iva_default_pct: float = 15.0) -> tuple[float, float, float]:
    """Calcula subtotal, iva, total desde items simple."""
    subtotal = 0.0
    iva_total = 0.0
    for it in items_json:
        cant = float(it.get("cantidad", 1))
        pu = float(it.get("precio_unitario", 0))
        iva_pct = float(it.get("iva_pct", iva_default_pct))
        base = cant * pu
        subtotal += base
        iva_total += base * iva_pct / 100.0
    return round(subtotal, 2), round(iva_total, 2), round(subtotal + iva_total, 2)


# ──────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────

class ItemPayload(BaseModel):
    descripcion: str = Field(..., min_length=1, max_length=300)
    cantidad: float = Field(default=1, gt=0)
    precio_unitario: float = Field(default=0, ge=0)
    iva_pct: float = Field(default=15.0, ge=0, le=100)
    codigo: Optional[str] = "GEN"
    descuento: float = Field(default=0, ge=0)


class BorradorCreate(BaseModel):
    empresa_id: int = Field(default=5, description="Fijo IMPORFACTORY=5")
    cliente_tipo_id: str = Field(default="cedula")
    cliente_identificacion: str = Field(..., min_length=1, max_length=20)
    cliente_razon_social: str = Field(..., min_length=2, max_length=220)
    cliente_email: Optional[str] = None
    cliente_telefono: Optional[str] = None
    cliente_direccion: Optional[str] = None
    items: list[ItemPayload] = Field(..., min_length=1)
    fuente: str = Field(default="form")

    @field_validator("cliente_tipo_id")
    @classmethod
    def _check_tipo(cls, v: str) -> str:
        if v not in {"cedula", "ruc", "pasaporte", "consumidor_final"}:
            raise ValueError("tipo_id invalido")
        return v


class BorradorUpdate(BaseModel):
    cliente_tipo_id: Optional[str] = None
    cliente_identificacion: Optional[str] = None
    cliente_razon_social: Optional[str] = None
    cliente_email: Optional[str] = None
    cliente_telefono: Optional[str] = None
    cliente_direccion: Optional[str] = None
    items: Optional[list[ItemPayload]] = None


class EmitirBatchPayload(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=200)


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.get("/info")
async def get_info(db_erp: AsyncSession = Depends(get_db_erp)):
    """Estado config Datil de IMPORFACTORY (eid=5)."""
    cfg = await dh.get_all_datil_config(db_erp, EMPRESA_ID)
    habilitado = bool(cfg.get("DATIL_API_KEY"))
    ambiente = int(cfg.get("DATIL_AMBIENTE", "1"))
    return {
        "empresa_id": EMPRESA_ID,
        "nombre": EMPRESA_INFO["nombre"],
        "ruc": cfg.get("DATIL_RUC", EMPRESA_INFO["ruc_display"]),
        "razon_social": cfg.get("DATIL_RAZON_SOCIAL", ""),
        "ambiente": ambiente,
        "punto_emision": cfg.get("DATIL_PUNTO_EMISION_PRODUCCION") if ambiente == 2 else cfg.get("DATIL_PUNTO_EMISION_PRUEBAS", "001"),
        "siguiente_numero": cfg.get("DATIL_SECUENCIAL_NEXT_PRODUCCION" if ambiente == 2 else "DATIL_SECUENCIAL_NEXT_PRUEBAS", "1"),
        "habilitado": habilitado,
        "missing_keys": [] if habilitado else [
            k for k in ["DATIL_API_KEY", "DATIL_CERT_PASSWORD", "DATIL_RUC", "DATIL_RAZON_SOCIAL",
                        "DATIL_ESTABLECIMIENTO_DEFAULT"] if not cfg.get(k)
        ],
    }


@router.post("/borrador")
async def crear_borrador(
    payload: BorradorCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    payload.empresa_id = EMPRESA_ID  # forzar IMPORFACTORY

    items_dicts = [it.model_dump() for it in payload.items]
    subtotal, iva, total = _calc_totales(items_dicts)

    res = await db.execute(text("""
        INSERT INTO facturas_borrador
            (empresa_id, cliente_tipo_id, cliente_identificacion, cliente_razon_social,
             cliente_email, cliente_telefono, cliente_direccion, items_json,
             subtotal, iva_valor, total, fuente, estado)
        VALUES
            (:eid, :tid, :iden, :razon, :email, :tel, :dir, :items,
             :sub, :iva, :tot, :fuente, 'borrador')
    """), {
        "eid": payload.empresa_id, "tid": payload.cliente_tipo_id,
        "iden": payload.cliente_identificacion.strip(),
        "razon": payload.cliente_razon_social.strip(),
        "email": (payload.cliente_email or "").strip() or None,
        "tel": (payload.cliente_telefono or "").strip() or None,
        "dir": (payload.cliente_direccion or "").strip() or None,
        "items": json.dumps(items_dicts),
        "sub": subtotal, "iva": iva, "tot": total,
        "fuente": payload.fuente,
    })
    await db.commit()
    return {"ok": True, "id": res.lastrowid, "subtotal": subtotal, "iva": iva, "total": total}


@router.get("/borradores")
async def listar_borradores(
    estado: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    where = ["empresa_id = :eid"]
    params = {"limit": limit, "eid": EMPRESA_ID}
    if estado:
        where.append("estado = :est")
        params["est"] = estado
    sql = f"""
        SELECT id, empresa_id, cliente_tipo_id, cliente_identificacion,
               cliente_razon_social, cliente_email, cliente_telefono, items_json,
               subtotal, iva_valor, total, estado, fuente, factura_numero,
               factura_autorizacion_sri, factura_pdf_url, factura_xml_url,
               error_msg, created_at, emitida_at
        FROM facturas_borrador
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC LIMIT :limit
    """
    rows = (await db.execute(text(sql), params)).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["items"] = json.loads(d.pop("items_json") or "[]")
        except Exception:
            d["items"] = []
        # Decimals → float
        for k in ("subtotal", "iva_valor", "total"):
            if d.get(k) is not None:
                d[k] = float(d[k])
        out.append(d)
    return {"items": out}


@router.put("/borrador/{borrador_id}")
async def editar_borrador(
    borrador_id: int,
    payload: BorradorUpdate,
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(text("""
        SELECT estado, items_json FROM facturas_borrador WHERE id = :id
    """), {"id": borrador_id})).first()
    if not row:
        raise HTTPException(404, "Borrador no encontrado")
    if row[0] in ("emitida", "emitiendo"):
        raise HTTPException(400, f"No se puede editar (estado={row[0]})")

    updates = {}
    if payload.cliente_tipo_id: updates["cliente_tipo_id"] = payload.cliente_tipo_id
    if payload.cliente_identificacion: updates["cliente_identificacion"] = payload.cliente_identificacion.strip()
    if payload.cliente_razon_social: updates["cliente_razon_social"] = payload.cliente_razon_social.strip()
    if payload.cliente_email is not None: updates["cliente_email"] = payload.cliente_email.strip() or None
    if payload.cliente_telefono is not None: updates["cliente_telefono"] = payload.cliente_telefono.strip() or None
    if payload.cliente_direccion is not None: updates["cliente_direccion"] = payload.cliente_direccion.strip() or None
    if payload.items:
        items_d = [it.model_dump() for it in payload.items]
        sub, iva, tot = _calc_totales(items_d)
        updates["items_json"] = json.dumps(items_d)
        updates["subtotal"] = sub
        updates["iva_valor"] = iva
        updates["total"] = tot

    if not updates:
        return {"ok": True, "msg": "Sin cambios"}

    set_clauses = ", ".join([f"{k} = :{k}" for k in updates])
    updates["_id"] = borrador_id
    await db.execute(text(f"UPDATE facturas_borrador SET {set_clauses} WHERE id = :_id"), updates)
    await db.commit()
    return {"ok": True}


@router.delete("/borrador/{borrador_id}")
async def eliminar_borrador(
    borrador_id: int,
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(text("SELECT estado FROM facturas_borrador WHERE id = :id"), {"id": borrador_id})).first()
    if not row:
        raise HTTPException(404, "No encontrado")
    if row[0] == "emitida":
        raise HTTPException(400, "No se puede eliminar una factura ya emitida")
    await db.execute(text("DELETE FROM facturas_borrador WHERE id = :id"), {"id": borrador_id})
    await db.commit()
    return {"ok": True}


# ──────────────────────────────────────────────
# Emisión (individual y batch)
# ──────────────────────────────────────────────

async def _emitir_una(db: AsyncSession, db_erp: AsyncSession, borrador_id: int) -> dict:
    """Emite UNA factura. Retorna resultado."""
    row = (await db.execute(text("""
        SELECT empresa_id, cliente_tipo_id, cliente_identificacion, cliente_razon_social,
               cliente_email, cliente_telefono, cliente_direccion, items_json, estado
        FROM facturas_borrador WHERE id = :id
    """), {"id": borrador_id})).mappings().first()
    if not row:
        return {"id": borrador_id, "ok": False, "error": "No encontrado"}
    if row["estado"] in ("emitida", "emitiendo"):
        return {"id": borrador_id, "ok": False, "error": f"Estado actual: {row['estado']}"}

    try:
        # Marca emitiendo
        await db.execute(text("""
            UPDATE facturas_borrador SET estado = 'emitiendo' WHERE id = :id
        """), {"id": borrador_id})
        await db.commit()

        # Config emisor
        emisor, ambiente, api_key, cert_password = await dh.get_emisor_y_ambiente(db_erp, row["empresa_id"])

        # Incrementar secuencial (atómico)
        secuencial = await dh.incrementar_secuencial(db_erp, row["empresa_id"], ambiente)

        # Comprador
        comprador = dh.build_comprador(
            tipo_id=row["cliente_tipo_id"],
            identificacion=row["cliente_identificacion"],
            razon_social=row["cliente_razon_social"],
            email=row["cliente_email"],
            telefono=row["cliente_telefono"],
            direccion=row["cliente_direccion"],
        )

        # Items
        items_raw = json.loads(row["items_json"] or "[]")
        items = dh.build_items_from_json(items_raw)

        # Payload Datil
        fecha = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        payload = datil.build_invoice_payload(
            secuencial=secuencial,
            emisor=emisor,
            comprador=comprador,
            items=items,
            fecha_emision=fecha,
            ambiente=ambiente,
            moneda="USD",
            info_adicional=[
                {"nombre": "emitido_por", "valor": "IMPORFACTORY-PREMIUM"},
                {"nombre": "borrador_id", "valor": str(borrador_id)},
            ],
        )

        # Emitir
        idempotency = f"borrador-{borrador_id}-{uuid.uuid4().hex[:8]}"
        resp = await datil.issue_invoice(api_key, payload, idempotency_key=idempotency, cert_password=cert_password)

        factura_id = resp.get("id") or resp.get("factura_id")
        numero = dh.numero_factura_completo(row["empresa_id"], emisor, secuencial)
        clave = resp.get("clave_acceso")
        estado_sri = resp.get("estado", "")
        autorizacion = resp.get("numero_autorizacion") or resp.get("autorizacion")

        await db.execute(text("""
            UPDATE facturas_borrador SET
                estado = 'emitida',
                factura_id_datil = :fid,
                factura_numero = :num,
                factura_clave_acceso = :clave,
                factura_autorizacion_sri = :auto,
                factura_estado_sri = :est,
                emitida_at = NOW(),
                error_msg = NULL
            WHERE id = :id
        """), {
            "fid": factura_id, "num": numero, "clave": clave, "auto": autorizacion,
            "est": estado_sri, "id": borrador_id,
        })
        await db.commit()
        return {"id": borrador_id, "ok": True, "numero": numero, "datil_id": factura_id}
    except Exception as e:
        err_msg = str(e)[:1500]
        await db.execute(text("""
            UPDATE facturas_borrador SET estado = 'fallo', error_msg = :err WHERE id = :id
        """), {"err": err_msg, "id": borrador_id})
        await db.commit()
        return {"id": borrador_id, "ok": False, "error": err_msg}


@router.post("/emitir-batch")
async def emitir_batch(
    payload: EmitirBatchPayload,
    db: AsyncSession = Depends(get_db),
    db_erp: AsyncSession = Depends(get_db_erp),
):
    """Emite las facturas IDs seleccionadas. Procesa secuencialmente para no chocar
    con el secuencial Datil. Retorna detalle por factura.
    """
    results = []
    ok = 0
    fail = 0
    for bid in payload.ids:
        r = await _emitir_una(db, db_erp, bid)
        results.append(r)
        if r["ok"]:
            ok += 1
        else:
            fail += 1
    return {"total": len(payload.ids), "ok": ok, "fail": fail, "items": results}


@router.post("/borrador/{borrador_id}/emitir")
async def emitir_individual(
    borrador_id: int,
    db: AsyncSession = Depends(get_db),
    db_erp: AsyncSession = Depends(get_db_erp),
):
    """Emite 1 factura."""
    r = await _emitir_una(db, db_erp, borrador_id)
    if not r["ok"]:
        raise HTTPException(400, r.get("error", "Fallo emision"))
    return r


# ═══════════════════════════════════════════════════════════
# ENDPOINT PÚBLICO (alumnos) — crea borrador desde form simple
# ═══════════════════════════════════════════════════════════

class FacturaAlumnoPayload(BaseModel):
    tipo_id: str = Field(default="cedula")
    identificacion: str = Field(..., max_length=20)
    nombre: str = Field(..., min_length=3, max_length=220)
    email: EmailStr
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    producto: str = Field(..., max_length=40)  # club|curso|asesoria|otro
    monto: float = Field(..., gt=0)
    descripcion: str = Field(..., max_length=300)
    fecha_pago: Optional[str] = None


@router.post("/factura/solicitar")
async def solicitar_factura_alumno(
    payload: FacturaAlumnoPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Endpoint PÚBLICO (sin auth) — alumno solicita factura.

    Crea borrador en facturas_borrador con fuente=form_alumno.
    Admin la revisa y emite desde /facturacion.
    """
    # Construir items_json (1 item con monto + IVA 15%)
    items = [{
        "descripcion": payload.descripcion[:300],
        "cantidad": 1,
        "precio_unitario": float(payload.monto),
        "iva_pct": 15.0,
        "codigo": payload.producto.upper(),
    }]
    sub, iva, tot = _calc_totales(items)

    res = await db.execute(text("""
        INSERT INTO facturas_borrador
            (empresa_id, cliente_tipo_id, cliente_identificacion, cliente_razon_social,
             cliente_email, cliente_telefono, cliente_direccion, items_json,
             subtotal, iva_valor, total, fuente, estado)
        VALUES
            (5, :tid, :iden, :razon, :email, :tel, :dir, :items,
             :sub, :iva, :tot, 'form_alumno', 'borrador')
    """), {
        "tid": payload.tipo_id,
        "iden": payload.identificacion.strip() or "9999999999999",
        "razon": payload.nombre.strip(),
        "email": str(payload.email),
        "tel": (payload.telefono or "").strip() or None,
        "dir": (payload.direccion or "").strip() or None,
        "items": json.dumps(items),
        "sub": sub, "iva": iva, "tot": tot,
    })
    await db.commit()

    return {
        "ok": True,
        "borrador_id": res.lastrowid,
        "mensaje": "Solicitud recibida. Te emitiremos la factura en menos de 24h",
    }
