"""
IMPORFACTORY Premium — Cliente de la API Carterachat (cobranzas IMPORSUIT).

API externa en https://new.imporsuitpro.com (plataforma IMPORSUIT, separada del ERP).
Router por convención /<Controller>/<metodo>/<param>. Envelope LEGACY:
    {status, message, count, data}
con HTTP 200 INCLUSO en error → hay que chequear body["status"], no r.status_code.

El token de integración se lee de env CARTERACHAT_TOKEN o de empresa_config(5).
Si no hay token o la API falla, get_ranking_cobranzas devuelve MOCK_RANKING para
que el tablero de TV nunca quede en blanco.

2026-06-06 Sprint 36.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

import httpx
from sqlalchemy import text

logger = logging.getLogger("carterachat")

BASE = "https://new.imporsuitpro.com"
TIMEOUT = 8.0

# Datos demo (closers reales del ERP) para construir/probar la TV sin token.
# Incluye VENDIDO (deudas creadas) y COBRADO (pagos) por asesor en el periodo.
MOCK_RANKING = [
    {"asesor": "Adrian", "total_vendido": 7300.0, "num_ventas": 15, "total_cobrado": 6840.0, "num_pagos": 23, "monto_vencido": 1200.0, "num_clientes": 31},
    {"asesor": "Eve",    "total_vendido": 6100.0, "num_ventas": 13, "total_cobrado": 5210.0, "num_pagos": 19, "monto_vencido": 800.0,  "num_clientes": 24},
    {"asesor": "Kathy",  "total_vendido": 3900.0, "num_ventas": 9,  "total_cobrado": 4980.0, "num_pagos": 18, "monto_vencido": 1500.0, "num_clientes": 22},
    {"asesor": "Karito", "total_vendido": 1450.0, "num_ventas": 4,  "total_cobrado": 730.0,  "num_pagos": 5,  "monto_vencido": 600.0,  "num_clientes": 9},
    {"asesor": "Diego",  "total_vendido": 700.0,  "num_ventas": 2,  "total_cobrado": 1890.0, "num_pagos": 8,  "monto_vencido": 2100.0, "num_clientes": 7},
]


async def _get_token() -> Optional[str]:
    """Token de integración: prioridad env, fallback empresa_config (BD ERP)."""
    tok = os.environ.get("CARTERACHAT_TOKEN")
    if tok:
        return tok
    try:
        from core.database import ErpAsyncSessionLocal
        async with ErpAsyncSessionLocal() as erp:
            row = (await erp.execute(text("""
                SELECT valor FROM empresa_config
                WHERE empresa_id = 5 AND clave = 'CARTERACHAT_TOKEN' LIMIT 1
            """))).first()
        return row[0] if row else None
    except Exception:
        return None


def _headers(token: str) -> dict:
    # El nombre exacto del header lo confirma Jey; por defecto Bearer.
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _normalize(x: dict) -> dict:
    return {
        "asesor": x.get("nombre_asesor") or x.get("asesor") or f"Asesor {x.get('id_asesor', '?')}",
        "total_vendido": float(x.get("total_vendido") or x.get("monto_vendido") or 0),
        "num_ventas": int(x.get("num_ventas") or x.get("num_deudas") or 0),
        "total_cobrado": float(x.get("total_cobrado") or 0),
        "num_pagos": int(x.get("num_pagos") or 0),
        "monto_vencido": float(x.get("monto_vencido") or x.get("monto_pendiente") or 0),
        "num_clientes": int(x.get("num_clientes") or 0),
    }


async def get_ranking_cobranzas(desde: str, hasta: str) -> dict:
    """Ranking de $ cobrado por asesor en [desde, hasta] (YYYY-MM-DD).

    Devuelve {"source": "api"|"mock", "items": [...], "api_error"?: str}.
    NUNCA lanza: si algo falla, cae a MOCK_RANKING para no romper la TV.
    """
    token = await _get_token()
    if not token:
        return {"source": "mock", "items": MOCK_RANKING, "api_error": "sin CARTERACHAT_TOKEN"}

    try:
        url = f"{BASE}/Carterachat/ranking_asesores"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url, headers=_headers(token),
                                  params={"desde": desde, "hasta": hasta})
            body = r.json() if r.content else {}
        # Envelope legacy: status interno, HTTP 200 aunque sea error
        if str(body.get("status")) == "200" and isinstance(body.get("data"), list):
            return {"source": "api", "items": [_normalize(x) for x in body["data"]]}
        msg = body.get("message") or f"status={body.get('status')}"
        logger.warning("Carterachat ranking sin datos: %s", str(msg)[:200])
        return {"source": "mock", "items": MOCK_RANKING, "api_error": str(msg)[:160]}
    except Exception as e:
        logger.warning("Carterachat error: %s", str(e)[:200])
        return {"source": "mock", "items": MOCK_RANKING, "api_error": str(e)[:160]}
