"""
IMPORFACTORY Premium — Servicio de métricas financieras.

Calcula KPIs ejecutivos (MRR, churn, LTV, cuentas por cobrar, etc.) leyendo:
  - alumno_membresias (membresías activas con monto_pagado)
  - alumnos (registros, churned, activos)
  - flujo_caja (ingresos/gastos por categoría)
  - finanzas_snapshots (cache calculado por cron)

Diseñado para ser barato: snapshot diario por cron + endpoint dashboard que lo lee.
El endpoint /snapshot-now permite forzar recálculo a demanda.

2026-05-27 Sprint 3.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# Precios estimados por tipo de membresía (USD/mes equivalente).
# Si en el futuro se centraliza en tabla precios_membresia, leer de ahí.
# Para MRR de pago único (kit), se considera $0 mensual recurrente.
PRECIO_ESTIMADO_MENSUAL = {
    "importacion": 47.0,   # estimado promedio mensual
    "ecommerce": 47.0,
    "infoaduana": 27.0,
    "kit": 0.0,            # pago único, no recurrente
}


async def compute_snapshot(db: AsyncSession, empresa_id: int = 5) -> dict:
    """Calcula todos los KPIs para una fecha (hoy) y retorna dict listo para insertar.

    Robusto a tablas vacías: campos NULL si no hay datos.
    """
    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    inicio_mes_pasado = (inicio_mes - timedelta(days=1)).replace(day=1)
    fin_mes_pasado = inicio_mes - timedelta(days=1)
    hace_30d = hoy - timedelta(days=30)
    hace_90d = hoy - timedelta(days=90)
    proximo_30d = hoy + timedelta(days=30)

    # ── 1. Alumnos: total, activos, nuevos del mes, vencidos 30d, proximos a vencer
    alumnos_row = (await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN activo=1 THEN 1 ELSE 0 END) AS activos,
            SUM(CASE WHEN DATE(fecha_registro) >= :inicio_mes THEN 1 ELSE 0 END) AS nuevos_mes
        FROM alumnos
        WHERE empresa_id = :emp
    """), {"emp": empresa_id, "inicio_mes": inicio_mes})).mappings().first()

    alumnos_activos = int(alumnos_row["activos"] or 0)
    alumnos_nuevos_mes = int(alumnos_row["nuevos_mes"] or 0)

    # ── 2. Membresías: por tipo + MRR estimado
    membresias_rows = (await db.execute(text("""
        SELECT tipo, COUNT(*) AS n, COALESCE(AVG(monto_pagado),0) AS prom_pago
        FROM alumno_membresias
        WHERE activa = 1
        GROUP BY tipo
    """))).mappings().all()

    breakdown = {}
    mrr = Decimal("0.00")
    for r in membresias_rows:
        tipo = r["tipo"]
        n = int(r["n"])
        breakdown[tipo] = n
        precio = PRECIO_ESTIMADO_MENSUAL.get(tipo, 0.0)
        mrr += Decimal(str(precio)) * Decimal(n)

    arr = mrr * Decimal("12")

    # ── 3. Membresías que vencen en próximos 30 días + vencidas hace 30 días
    venc_proximos = (await db.execute(text("""
        SELECT COUNT(*) AS n
        FROM alumno_membresias
        WHERE activa = 1
          AND fecha_vencimiento IS NOT NULL
          AND DATE(fecha_vencimiento) BETWEEN :hoy AND :proximo_30d
    """), {"hoy": hoy, "proximo_30d": proximo_30d})).scalar()

    venc_pasados = (await db.execute(text("""
        SELECT COUNT(*) AS n
        FROM alumno_membresias
        WHERE activa = 0
          AND fecha_vencimiento IS NOT NULL
          AND DATE(fecha_vencimiento) BETWEEN :hace_30d AND :hoy
    """), {"hoy": hoy, "hace_30d": hace_30d})).scalar()

    # ── 4. Churn: vencidos / (vencidos + activos) en ventana
    activos_inicio_30d = (await db.execute(text("""
        SELECT COUNT(*) AS n
        FROM alumno_membresias
        WHERE (activa = 1 AND fecha_inicio <= :hace_30d)
           OR (activa = 0 AND fecha_vencimiento >= :hace_30d AND fecha_vencimiento <= :hoy)
    """), {"hace_30d": hace_30d, "hoy": hoy})).scalar() or 0

    churn_30d = float(int(venc_pasados or 0)) / max(int(activos_inicio_30d or 1), 1)
    churn_30d = min(churn_30d, 1.0)

    # ── 5. LTV simplificado: monto_pagado_promedio_lifetime
    ltv_row = (await db.execute(text("""
        SELECT
            COALESCE(AVG(am.monto_pagado), 0) AS prom_monto,
            COUNT(DISTINCT am.alumno_id) AS n_alumnos
        FROM alumno_membresias am
        WHERE am.monto_pagado IS NOT NULL AND am.monto_pagado > 0
    """))).mappings().first()
    ltv = Decimal(str(float(ltv_row["prom_monto"] or 0)))

    # ── 6. Flujo de caja: ingresos/gastos del mes
    flujo_mes = (await db.execute(text("""
        SELECT
            COALESCE(SUM(CASE WHEN tipo='INGRESO' THEN monto ELSE 0 END), 0) AS ingresos,
            COALESCE(SUM(CASE WHEN tipo='EGRESO'  THEN monto ELSE 0 END), 0) AS gastos
        FROM flujo_caja
        WHERE empresa_id = :emp AND fecha >= :inicio_mes
    """), {"emp": empresa_id, "inicio_mes": inicio_mes})).mappings().first()

    flujo_mes_pasado = (await db.execute(text("""
        SELECT COALESCE(SUM(CASE WHEN tipo='INGRESO' THEN monto ELSE 0 END), 0) AS ingresos
        FROM flujo_caja
        WHERE empresa_id = :emp AND fecha BETWEEN :inicio_mp AND :fin_mp
    """), {"emp": empresa_id, "inicio_mp": inicio_mes_pasado, "fin_mp": fin_mes_pasado})).mappings().first()

    ingresos_mes = Decimal(str(float(flujo_mes["ingresos"] or 0)))
    gastos_mes = Decimal(str(float(flujo_mes["gastos"] or 0)))
    utilidad = ingresos_mes - gastos_mes
    margen = (utilidad / ingresos_mes * 100) if ingresos_mes > 0 else Decimal("0")
    ingresos_mes_pasado = Decimal(str(float(flujo_mes_pasado["ingresos"] or 0)))

    # ── 7. Stripe subscriptions activas (proxy: stripe_subscription_id NOT NULL)
    stripe_count = (await db.execute(text("""
        SELECT COUNT(*) FROM alumno_membresias
        WHERE activa = 1 AND stripe_subscription_id IS NOT NULL
    """))).scalar() or 0

    # ── 8. Cuentas por cobrar: pendiente de cobro = (alumnos.cuotas_monto_pendiente si existe)
    # Fallback: 0 si la columna no existe.
    cxc = Decimal("0.00")
    try:
        cxc_val = (await db.execute(text("""
            SELECT COALESCE(SUM(cuotas_monto_pendiente), 0) FROM alumnos
            WHERE empresa_id = :emp AND activo = 1
        """), {"emp": empresa_id})).scalar()
        cxc = Decimal(str(float(cxc_val or 0)))
    except Exception:
        cxc = Decimal("0.00")

    # ── 9. Costo AI 30d
    costo_ai = (await db.execute(text("""
        SELECT COALESCE(SUM(costo_usd), 0) FROM blog_generaciones_ai
        WHERE generado_en >= :hace_30d
    """), {"hace_30d": hace_30d})).scalar() or 0

    return {
        "empresa_id": empresa_id,
        "fecha": hoy,
        "mrr": float(mrr),
        "arr": float(arr),
        "ingresos_mes": float(ingresos_mes),
        "ingresos_mes_pasado": float(ingresos_mes_pasado),
        "gastos_mes": float(gastos_mes),
        "utilidad": float(utilidad),
        "margen_pct": float(margen),
        "churn_rate_30d": float(churn_30d),
        "churn_rate_90d": None,  # calculable similar a 30d, omitido por simplicidad
        "ltv": float(ltv),
        "cac_estimado": None,
        "alumnos_activos": alumnos_activos,
        "alumnos_nuevos_mes": alumnos_nuevos_mes,
        "alumnos_vencidos_30d": int(venc_pasados or 0),
        "alumnos_proximos_vencer_30d": int(venc_proximos or 0),
        "cuentas_por_cobrar": float(cxc),
        "suscripciones_stripe_activas": int(stripe_count),
        "breakdown_membresias_json": breakdown,
        "costo_ai_30d": float(costo_ai),
        "calculado_en": datetime.utcnow(),
    }


async def upsert_snapshot(db: AsyncSession, snap: dict) -> int:
    """UPSERT a finanzas_snapshots usando UNIQUE (empresa_id, fecha)."""
    import json
    breakdown_json = json.dumps(snap.get("breakdown_membresias_json") or {})

    await db.execute(text("""
        INSERT INTO finanzas_snapshots (
            empresa_id, fecha, mrr, arr, ingresos_mes, ingresos_mes_pasado,
            gastos_mes, utilidad, margen_pct, churn_rate_30d, churn_rate_90d,
            ltv, cac_estimado, alumnos_activos, alumnos_nuevos_mes,
            alumnos_vencidos_30d, alumnos_proximos_vencer_30d,
            cuentas_por_cobrar, suscripciones_stripe_activas,
            breakdown_membresias_json, costo_ai_30d, calculado_en
        ) VALUES (
            :empresa_id, :fecha, :mrr, :arr, :ingresos_mes, :ingresos_mes_pasado,
            :gastos_mes, :utilidad, :margen_pct, :churn_rate_30d, :churn_rate_90d,
            :ltv, :cac_estimado, :alumnos_activos, :alumnos_nuevos_mes,
            :alumnos_vencidos_30d, :alumnos_proximos_vencer_30d,
            :cuentas_por_cobrar, :suscripciones_stripe_activas,
            :breakdown_json, :costo_ai_30d, :calculado_en
        )
        ON DUPLICATE KEY UPDATE
            mrr = VALUES(mrr),
            arr = VALUES(arr),
            ingresos_mes = VALUES(ingresos_mes),
            ingresos_mes_pasado = VALUES(ingresos_mes_pasado),
            gastos_mes = VALUES(gastos_mes),
            utilidad = VALUES(utilidad),
            margen_pct = VALUES(margen_pct),
            churn_rate_30d = VALUES(churn_rate_30d),
            churn_rate_90d = VALUES(churn_rate_90d),
            ltv = VALUES(ltv),
            cac_estimado = VALUES(cac_estimado),
            alumnos_activos = VALUES(alumnos_activos),
            alumnos_nuevos_mes = VALUES(alumnos_nuevos_mes),
            alumnos_vencidos_30d = VALUES(alumnos_vencidos_30d),
            alumnos_proximos_vencer_30d = VALUES(alumnos_proximos_vencer_30d),
            cuentas_por_cobrar = VALUES(cuentas_por_cobrar),
            suscripciones_stripe_activas = VALUES(suscripciones_stripe_activas),
            breakdown_membresias_json = VALUES(breakdown_membresias_json),
            costo_ai_30d = VALUES(costo_ai_30d),
            calculado_en = VALUES(calculado_en)
    """), {**snap, "breakdown_json": breakdown_json})
    await db.commit()

    result = await db.execute(text("""
        SELECT id FROM finanzas_snapshots WHERE empresa_id = :emp AND fecha = :fecha
    """), {"emp": snap["empresa_id"], "fecha": snap["fecha"]})
    row = result.first()
    return int(row[0]) if row else 0


async def get_latest_snapshot(db: AsyncSession, empresa_id: int = 5) -> Optional[dict]:
    """Retorna el snapshot más reciente. None si no hay ninguno."""
    row = (await db.execute(text("""
        SELECT * FROM finanzas_snapshots
        WHERE empresa_id = :emp
        ORDER BY fecha DESC LIMIT 1
    """), {"emp": empresa_id})).mappings().first()
    return dict(row) if row else None


async def get_mrr_historico(db: AsyncSession, empresa_id: int = 5, dias: int = 90) -> list[dict]:
    """Serie temporal de MRR. Devuelve [{fecha, mrr}]."""
    rows = (await db.execute(text("""
        SELECT fecha, mrr, alumnos_activos
        FROM finanzas_snapshots
        WHERE empresa_id = :emp AND fecha >= DATE_SUB(CURDATE(), INTERVAL :dias DAY)
        ORDER BY fecha ASC
    """), {"emp": empresa_id, "dias": dias})).mappings().all()
    return [dict(r) for r in rows]
