"""Wrapper sobre services/datil.py que lee credenciales de la BD ERP (grupo_impor.empresa_config)
en lugar de usar el modelo SQLAlchemy `EmpresaConfig` que vive en el ERP repo.

Reusa todas las funciones de Datil API (services/datil.py) — solo cambia el origen de las creds.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ──────────────────────────────────────────────
# Lee config desde la BD ERP (grupo_impor)
# El AsyncSession debe ser el "erp" (via get_db_erp)
# ──────────────────────────────────────────────

async def get_config(db_erp: AsyncSession, empresa_id: int, clave: str) -> Optional[str]:
    row = (await db_erp.execute(text("""
        SELECT valor FROM empresa_config
        WHERE empresa_id = :e AND clave = :k
        LIMIT 1
    """), {"e": empresa_id, "k": clave})).first()
    return row[0] if row else None


async def get_all_datil_config(db_erp: AsyncSession, empresa_id: int) -> dict:
    """Devuelve dict con TODOS los DATIL_* config de una empresa."""
    rows = (await db_erp.execute(text("""
        SELECT clave, valor FROM empresa_config
        WHERE empresa_id = :e AND clave LIKE 'DATIL_%'
    """), {"e": empresa_id})).mappings().all()
    return {r["clave"]: r["valor"] for r in rows}


async def set_config(db_erp: AsyncSession, empresa_id: int, clave: str, valor: str) -> None:
    await db_erp.execute(text("""
        INSERT INTO empresa_config (empresa_id, clave, valor)
        VALUES (:e, :k, :v)
        ON DUPLICATE KEY UPDATE valor = VALUES(valor), updated_at = NOW()
    """), {"e": empresa_id, "k": clave, "v": valor})
    await db_erp.commit()


async def incrementar_secuencial(db_erp: AsyncSession, empresa_id: int, ambiente: int) -> int:
    """Lee, incrementa y persiste el secuencial. Atómico (transacción individual).

    ambiente: 1=pruebas, 2=produccion
    """
    clave = "DATIL_SECUENCIAL_NEXT_PRODUCCION" if ambiente == 2 else "DATIL_SECUENCIAL_NEXT_PRUEBAS"
    actual = await get_config(db_erp, empresa_id, clave) or "1"
    try:
        n = int(actual)
    except ValueError:
        n = 1
    siguiente = n + 1
    await set_config(db_erp, empresa_id, clave, str(siguiente))
    return n


async def get_emisor_y_ambiente(db_erp: AsyncSession, empresa_id: int) -> tuple[dict, int, str, str]:
    """Construye el dict 'emisor' (Datil) + ambiente + api_key + cert_password.

    Returns: (emisor_dict, ambiente, api_key, cert_password)
    Raises RuntimeError si falta config crítica.
    """
    cfg = await get_all_datil_config(db_erp, empresa_id)
    if not cfg.get("DATIL_API_KEY"):
        raise RuntimeError(f"empresa_id={empresa_id} NO tiene DATIL_API_KEY configurado. Cargá las credenciales Datil en empresa_config.")

    ambiente = int(cfg.get("DATIL_AMBIENTE", "1"))
    if cfg.get("DATIL_HABILITADO", "false").lower() not in ("true", "1", "si", "sí", "yes"):
        # No bloquea — solo warning
        pass

    emisor = {
        "ruc": cfg.get("DATIL_RUC", ""),
        "razon_social": cfg.get("DATIL_RAZON_SOCIAL", ""),
        "nombre_comercial": cfg.get("DATIL_NOMBRE_COMERCIAL") or cfg.get("DATIL_RAZON_SOCIAL", ""),
        "obligado_contabilidad": cfg.get("DATIL_OBLIGADO_CONTABILIDAD", "NO").upper(),
        "establecimiento": {
            "codigo": cfg.get("DATIL_ESTABLECIMIENTO_DEFAULT", "001"),
            "punto_emision": (cfg.get("DATIL_PUNTO_EMISION_PRODUCCION") if ambiente == 2
                              else cfg.get("DATIL_PUNTO_EMISION_PRUEBAS", "001")),
            "direccion": cfg.get("DATIL_DIRECCION_MATRIZ", ""),
        },
    }
    return emisor, ambiente, cfg["DATIL_API_KEY"], cfg.get("DATIL_CERT_PASSWORD", "")


def build_comprador(tipo_id: str, identificacion: str, razon_social: str,
                    email: Optional[str] = None, telefono: Optional[str] = None,
                    direccion: Optional[str] = None) -> dict:
    """Construye dict comprador para Datil.

    tipo_id: cedula | ruc | pasaporte | consumidor_final
    """
    TIPO_MAP = {
        "cedula": "05",
        "ruc": "04",
        "pasaporte": "06",
        "consumidor_final": "07",
    }
    return {
        "tipo_identificacion": TIPO_MAP.get(tipo_id, "07"),
        "identificacion": identificacion.strip() if tipo_id != "consumidor_final" else "9999999999999",
        "razon_social": razon_social.strip() if razon_social else "CONSUMIDOR FINAL",
        "email": [email.strip()] if email else [],
        "telefono": telefono.strip() if telefono else "",
        "direccion": direccion.strip() if direccion else "",
    }


def build_items_from_json(items_json: list[dict], iva_default_pct: float = 15.0) -> list[dict]:
    """Convierte una lista de items simple {descripcion, cantidad, precio_unitario, iva_pct}
    al formato exacto de Datil con impuestos calculados.
    """
    result = []
    for it in items_json:
        cantidad = float(it.get("cantidad", 1))
        pu = float(it.get("precio_unitario", 0))
        iva_pct = float(it.get("iva_pct", iva_default_pct))
        base = round(cantidad * pu, 2)
        iva_valor = round(base * iva_pct / 100.0, 2)

        # Datil codigo_porcentaje: 0=0%, 2=12%, 4=15%, 3=14%
        codigo_pct = "0"
        if iva_pct == 12:   codigo_pct = "2"
        elif iva_pct == 14: codigo_pct = "3"
        elif iva_pct == 15: codigo_pct = "4"

        result.append({
            "codigo_principal": it.get("codigo", "GEN"),
            "descripcion": str(it.get("descripcion", ""))[:300],
            "cantidad": cantidad,
            "precio_unitario": pu,
            "precio_total_sin_impuestos": base,
            "descuento": float(it.get("descuento", 0)),
            "impuestos": [{
                "codigo": "2",  # IVA
                "codigo_porcentaje": codigo_pct,
                "tarifa": iva_pct,
                "base_imponible": base,
                "valor": iva_valor,
            }],
        })
    return result


def formato_secuencial(n: int) -> str:
    """Datil acepta el secuencial como int, pero el formato visible es 000000123."""
    return f"{int(n):09d}"


def numero_factura_completo(empresa_id: int, emisor: dict, secuencial_int: int) -> str:
    """Genera string 001-002-000000123 (establecimiento-punto-secuencial)."""
    e = emisor.get("establecimiento", {})
    cod = e.get("codigo", "001")
    pe = e.get("punto_emision", "002")
    return f"{cod}-{pe}-{formato_secuencial(secuencial_int)}"
