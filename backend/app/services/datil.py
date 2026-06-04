"""
GRUPO IMPOR — Servicio Datil (facturación electrónica SRI Ecuador)

Cliente HTTP para la API Datil Link (https://link.datil.co).
- Multi-empresa: cada RUC tiene su propia API key (guardada en empresa_config.DATIL_API_KEY)
- Idempotencia: usa Idempotency-Key para evitar duplicados en reintentos
- Devuelve siempre dicts uniformes: {ok, data?, error?}
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import EmpresaConfig

logger = logging.getLogger(__name__)

DATIL_BASE = "https://link.datil.co"
TIMEOUT = 30.0


# ════════════════════════════════════════════════════════════════
# Auth helper
# ════════════════════════════════════════════════════════════════

async def get_api_key(db: AsyncSession, empresa_id: int) -> Optional[str]:
    """Lee la API key de Datil de empresa_config para una empresa."""
    r = await db.execute(
        select(EmpresaConfig).where(
            EmpresaConfig.empresa_id == empresa_id,
            EmpresaConfig.clave == "DATIL_API_KEY",
        )
    )
    cfg = r.scalar_one_or_none()
    return cfg.valor if cfg and cfg.valor else None


async def get_cert_password(db: AsyncSession, empresa_id: int) -> Optional[str]:
    """Lee la contraseña del certificado .p12 (header X-Password de Datil)."""
    r = await db.execute(
        select(EmpresaConfig).where(
            EmpresaConfig.empresa_id == empresa_id,
            EmpresaConfig.clave == "DATIL_CERT_PASSWORD",
        )
    )
    cfg = r.scalar_one_or_none()
    return cfg.valor if cfg and cfg.valor else None


async def get_credentials(db: AsyncSession, empresa_id: int) -> tuple[Optional[str], Optional[str]]:
    """Devuelve (api_key, cert_password) para una empresa."""
    return await get_api_key(db, empresa_id), await get_cert_password(db, empresa_id)


def _headers(api_key: str, idempotency_key: Optional[str] = None, cert_password: Optional[str] = None) -> dict:
    h = {
        "X-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if cert_password:
        h["X-Password"] = cert_password
    if idempotency_key:
        h["Idempotency-Key"] = idempotency_key
    return h


# ════════════════════════════════════════════════════════════════
# Operaciones
# ════════════════════════════════════════════════════════════════

async def issue_invoice(api_key: str, payload: dict, idempotency_key: Optional[str] = None, cert_password: Optional[str] = None) -> dict:
    """
    Emite una factura electrónica via Datil Link.
    payload sigue el schema de Datil (fecha_emision, emisor, comprador, items, totales, etc.)
    cert_password: contraseña del .p12 (header X-Password — REQUERIDO por Datil)
    """
    url = f"{DATIL_BASE}/invoices/issue"
    idem = idempotency_key or str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(url, headers=_headers(api_key, idem, cert_password), json=payload)
            data = r.json() if r.content else {}
            if r.status_code in (200, 201):
                return {"ok": True, "data": data, "idempotency_key": idem}
            # F175.4: loggear el cuerpo crudo del rechazo para diagnostico del 400
            logger.error("Datil rechazo HTTP %s en %s | respuesta=%s", r.status_code, url, str(data)[:2000])
            return {
                "ok": False,
                "status": r.status_code,
                "error": data.get("errors") or data.get("message") or "Error desconocido",
                "raw": data,
                "idempotency_key": idem,
            }
    except httpx.HTTPError as e:
        logger.error("Datil HTTP error: %s", e)
        return {"ok": False, "error": f"Network error: {e}"}


async def get_invoice(api_key: str, invoice_id: str, cert_password: Optional[str] = None) -> dict:
    """Consulta una factura por ID Datil (no clave de acceso SRI)."""
    url = f"{DATIL_BASE}/invoices/{invoice_id}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url, headers=_headers(api_key, cert_password=cert_password))
            data = r.json() if r.content else {}
            if r.status_code == 200:
                return {"ok": True, "data": data}
            return {"ok": False, "status": r.status_code, "error": data}
    except httpx.HTTPError as e:
        return {"ok": False, "error": str(e)}


async def get_invoice_pdf(api_key: str, invoice_id: str, cert_password: Optional[str] = None) -> Optional[bytes]:
    """Descarga el RIDE PDF de una factura emitida."""
    url = f"{DATIL_BASE}/invoices/{invoice_id}/pdf"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url, headers=_headers(api_key, cert_password=cert_password))
            if r.status_code == 200 and r.content:
                return r.content
    except httpx.HTTPError:
        pass
    return None


async def get_invoice_xml(api_key: str, invoice_id: str, cert_password: Optional[str] = None) -> Optional[bytes]:
    """Descarga el XML firmado de una factura."""
    url = f"{DATIL_BASE}/invoices/{invoice_id}/xml"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url, headers=_headers(api_key, cert_password=cert_password))
            if r.status_code == 200 and r.content:
                return r.content
    except httpx.HTTPError:
        pass
    return None


async def cancel_invoice(api_key: str, invoice_id: str, motivo: str, cert_password: Optional[str] = None) -> dict:
    """Anula una factura emitida (genera nota de crédito o anulación SRI)."""
    url = f"{DATIL_BASE}/invoices/{invoice_id}/cancel"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(url, headers=_headers(api_key, cert_password=cert_password), json={"motivo": motivo})
            data = r.json() if r.content else {}
            return {"ok": r.status_code in (200, 202), "data": data, "status": r.status_code}
    except httpx.HTTPError as e:
        return {"ok": False, "error": str(e)}


async def health_check(db: AsyncSession, empresa_id: int) -> dict:
    """Verifica que la API key sea válida (POST con body vacío → 400 con MISSING_PARAMETER prueba auth OK)."""
    api_key, cert_password = await get_credentials(db, empresa_id)
    if not api_key:
        return {"ok": False, "error": "API key no configurada"}
    url = f"{DATIL_BASE}/invoices/issue"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, headers=_headers(api_key, cert_password=cert_password), json={})
            # 400 con MISSING_PARAMETER = key valida (la rechaza por body vacío pero pasó auth)
            # 401/403 = key inválida
            if r.status_code == 401 or r.status_code == 403:
                return {"ok": False, "auth": False, "error": "API key inválida"}
            return {
                "ok": True,
                "auth": True,
                "status": r.status_code,
                "key_preview": api_key[:8] + "...",
                "cert_password_set": bool(cert_password),
            }
    except httpx.HTTPError as e:
        return {"ok": False, "error": str(e)}


# ════════════════════════════════════════════════════════════════
# Helpers para construir payload desde una venta del ERP
# ════════════════════════════════════════════════════════════════

def build_invoice_payload(
    *,
    secuencial: str,
    emisor: dict,
    comprador: dict,
    items: list[dict],
    fecha_emision: str,
    ambiente: int = 1,  # 1=pruebas, 2=producción
    moneda: str = "USD",
    tipo_emision: int = 1,
    info_adicional=None,  # F175.4: lista [{nombre, valor}] (Datil), dict legacy tolerado
) -> dict:
    """
    Construye payload Datil-compatible.
    Schema real validado contra link.datil.co (Abr 2026):
      - moneda: "USD" o "EUR" (NO "DOLAR")
      - emisor: SIN direccion_matriz (Datil la toma del cert)
      - items: SIN codigo_iva, con impuestos[]
      - totales.descuento: REQUERIDO (0 si no hay)
    """
    # Calcular totales desde items
    subtotal_sin_impuestos = 0.0
    total_iva = 0.0
    total_descuento = 0.0
    impuestos_breakdown = {}  # {(cod, pct): {base, valor}}

    for it in items:
        sub = float(it.get("precio_total_sin_impuestos", 0))
        desc = float(it.get("descuento", 0))
        subtotal_sin_impuestos += sub
        total_descuento += desc
        for imp in it.get("impuestos", []):
            key = (str(imp.get("codigo", "2")), str(imp.get("codigo_porcentaje", "2")))
            agg = impuestos_breakdown.setdefault(key, {"base": 0.0, "valor": 0.0, "tarifa": imp.get("tarifa", 12)})
            agg["base"] += float(imp.get("base_imponible", 0))
            agg["valor"] += float(imp.get("valor", 0))
            total_iva += float(imp.get("valor", 0))

    total_sin_impuestos = round(subtotal_sin_impuestos, 2)
    total_iva = round(total_iva, 2)
    total = round(total_sin_impuestos + total_iva, 2)

    impuestos_arr = [
        {
            "codigo": cod,
            "codigo_porcentaje": pct,
            "base_imponible": round(agg["base"], 2),
            "valor": round(agg["valor"], 2),
        }
        for (cod, pct), agg in impuestos_breakdown.items()
    ] or [
        {"codigo": "2", "codigo_porcentaje": "2", "base_imponible": total_sin_impuestos, "valor": total_iva}
    ]

    # Items: limpiar codigo_iva (no permitido por Datil)
    clean_items = []
    for it in items:
        ci = {k: v for k, v in it.items() if k != "codigo_iva"}
        clean_items.append(ci)

    payload = {
        "secuencial": int(secuencial) if isinstance(secuencial, str) and secuencial.isdigit() else secuencial,
        "fecha_emision": fecha_emision,
        "ambiente": ambiente,
        "tipo_emision": tipo_emision,
        "moneda": moneda,
        "emisor": emisor,
        "comprador": comprador,
        "items": clean_items,
        "totales": {
            "total_sin_impuestos": total_sin_impuestos,
            "descuento": round(total_descuento, 2),
            "impuestos": impuestos_arr,
            "importe_total": total,
            "propina": 0.0,
        },
        "pagos": [
            {"medio": "efectivo", "total": total}
        ],
    }
    # F175.4 norm: Datil exige info_adicional como LISTA de {nombre, valor}.
    _ia = info_adicional
    if isinstance(_ia, dict):
        _ia = [{"nombre": str(k), "valor": str(v)} for k, v in _ia.items()
               if not isinstance(v, (list, dict))]
    if isinstance(_ia, list):
        _ia = [{"nombre": str(d.get("nombre"))[:300], "valor": str(d.get("valor"))[:300]}
               for d in _ia if isinstance(d, dict) and d.get("nombre") and d.get("valor") not in (None, "")]
        if _ia:
            payload["info_adicional"] = _ia
    return payload
