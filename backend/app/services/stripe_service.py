"""
IMPORFACTORY Premium — Wrapper Stripe Checkout para el lanzamiento IMPORCHAT.

Crea Checkout Sessions vía la REST API de Stripe usando httpx (mismo patrón
que openai_images_service.py), sin depender del SDK `stripe`. Lee la clave
secreta desde STRIPE_SECRET_KEY (env o empresa_config, empresa_id=5).

Ofertas (según Playbook de Lanzamiento IMPORCHAT):
  - principal : $297 pago único — Implementación Completa + 1 año de sistema.
  - cuotas    : 3 × $109 = $327 — mismo paquete, suscripción mensual (3 cargos).
  - lite      : $197 pago único — IMPORCHAT LITE (downsell, 6 meses, sin 1-1).

2026-06-19.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STRIPE_API_BASE = "https://api.stripe.com/v1"

# ── Catálogo de ofertas del webinar ──────────────────────────────────
# Los montos están en centavos de USD (Stripe trabaja en la unidad mínima).
OFERTAS: dict[str, dict] = {
    "principal": {
        "nombre": "IMPORCHAT — Implementación Completa + 1 Año de Sistema",
        "descripcion": (
            "Sistema ImporChat 12 meses (Kanban + Agentes IA + WhatsApp API), "
            "setup técnico, agente vendedor con file_search, 3 remarketing "
            "automáticos, capacitación 1-1 y todos los bonos del webinar."
        ),
        "monto_centavos": 29700,   # $297.00
        "mode": "payment",
        "cuotas_total": None,
    },
    "cuotas": {
        "nombre": "IMPORCHAT — Plan de Pagos (3 cuotas de $109)",
        "descripcion": (
            "Exactamente el mismo paquete completo, pagado en 3 cuotas "
            "mensuales de $109 ($327 total). Mismos bonos, misma garantía."
        ),
        "monto_centavos": 10900,   # $109.00 / mes × 3
        "mode": "subscription",
        "recurring_interval": "month",
        "cuotas_total": 3,
    },
    "lite": {
        "nombre": "IMPORCHAT LITE — 6 meses (auto-implementación)",
        "descripcion": (
            "Sistema ImporChat 6 meses + comunidad privada. Lo configuras tú "
            "con los tutoriales en video. Sin implementación 1-1 ni bonos premium."
        ),
        "monto_centavos": 19700,   # $197.00
        "mode": "payment",
        "cuotas_total": None,
    },
}


# ── Credenciales ──────────────────────────────────────────────────────
async def _get_secret_key(db: AsyncSession, empresa_id: int = 5) -> Optional[str]:
    """STRIPE_SECRET_KEY: prioridad env, fallback empresa_config (BD ERP)."""
    env_key = os.environ.get("STRIPE_SECRET_KEY")
    if env_key:
        return env_key
    try:
        from core.database import ErpAsyncSessionLocal
        async with ErpAsyncSessionLocal() as erp:
            row = (await erp.execute(text("""
                SELECT valor FROM empresa_config
                WHERE empresa_id = :emp AND clave = 'STRIPE_SECRET_KEY'
                LIMIT 1
            """), {"emp": empresa_id})).first()
        return row[0] if row else None
    except Exception:
        return None


async def _get_webhook_secret(db: AsyncSession, empresa_id: int = 5) -> Optional[str]:
    """STRIPE_WEBHOOK_SECRET para verificar la firma de los eventos."""
    env_key = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if env_key:
        return env_key
    try:
        from core.database import ErpAsyncSessionLocal
        async with ErpAsyncSessionLocal() as erp:
            row = (await erp.execute(text("""
                SELECT valor FROM empresa_config
                WHERE empresa_id = :emp AND clave = 'STRIPE_WEBHOOK_SECRET'
                LIMIT 1
            """), {"emp": empresa_id})).first()
        return row[0] if row else None
    except Exception:
        return None


# ── Helpers REST ──────────────────────────────────────────────────────
def _flatten(prefix: str, value, out: dict) -> None:
    """Aplana dict/list anidados a la notación form de Stripe: a[b][0][c]=v."""
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}[{k}]" if prefix else k, v, out)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    elif value is None:
        return
    elif isinstance(value, bool):
        out[prefix] = "true" if value else "false"
    else:
        out[prefix] = str(value)


# ── Checkout ──────────────────────────────────────────────────────────
async def create_checkout_session(
    db: AsyncSession,
    *,
    plan: str,
    success_url: str,
    cancel_url: str,
    email: Optional[str] = None,
    client_reference_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Crea una Checkout Session de Stripe y devuelve {id, url, plan, ...}.

    Raises RuntimeError si el plan es inválido o falta STRIPE_SECRET_KEY.
    """
    oferta = OFERTAS.get(plan)
    if not oferta:
        raise ValueError(f"Plan inválido: {plan!r}. Use principal | cuotas | lite.")

    api_key = await _get_secret_key(db)
    if not api_key:
        raise RuntimeError(
            "STRIPE_SECRET_KEY no configurada (env o empresa_config empresa_id=5). "
            "Configúrala antes de habilitar el checkout."
        )

    price_data: dict = {
        "currency": "usd",
        "unit_amount": oferta["monto_centavos"],
        "product_data": {
            "name": oferta["nombre"],
            "description": oferta["descripcion"],
        },
    }
    if oferta["mode"] == "subscription":
        price_data["recurring"] = {"interval": oferta.get("recurring_interval", "month")}

    payload: dict = {
        "mode": oferta["mode"],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "line_items": [{"price_data": price_data, "quantity": 1}],
        "allow_promotion_codes": True,
        "metadata": {
            "producto": "imporchat",
            "plan": plan,
            **(metadata or {}),
        },
    }
    if email:
        payload["customer_email"] = email
    if client_reference_id:
        payload["client_reference_id"] = client_reference_id

    if oferta["mode"] == "subscription":
        # Marcar las cuotas para que el webhook cancele la suscripción tras la 3ª.
        payload["subscription_data"] = {
            "metadata": {
                "producto": "imporchat",
                "plan": plan,
                "cuotas_total": oferta["cuotas_total"],
            }
        }
    else:
        payload["payment_intent_data"] = {
            "metadata": {"producto": "imporchat", "plan": plan}
        }

    form: dict = {}
    for k, v in payload.items():
        _flatten(k, v, form)

    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(
            f"{STRIPE_API_BASE}/checkout/sessions",
            data=form,
            auth=(api_key, ""),
        )
    if r.status_code >= 400:
        raise RuntimeError(f"Stripe error {r.status_code}: {r.text[:500]}")
    data = r.json()
    return {
        "id": data["id"],
        "url": data["url"],
        "plan": plan,
        "mode": oferta["mode"],
        "monto_centavos": oferta["monto_centavos"],
        "cuotas_total": oferta["cuotas_total"],
    }


async def retrieve_session(db: AsyncSession, session_id: str) -> dict:
    """Recupera una Checkout Session (para la página de gracias / confirmación)."""
    api_key = await _get_secret_key(db)
    if not api_key:
        raise RuntimeError("STRIPE_SECRET_KEY no configurada.")
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.get(
            f"{STRIPE_API_BASE}/checkout/sessions/{session_id}",
            params={"expand[]": "subscription"},
            auth=(api_key, ""),
        )
    if r.status_code >= 400:
        raise RuntimeError(f"Stripe error {r.status_code}: {r.text[:500]}")
    return r.json()


async def cancel_subscription(db: AsyncSession, subscription_id: str) -> dict:
    """Cancela una suscripción (usado al completar las 3 cuotas del plan de pagos)."""
    api_key = await _get_secret_key(db)
    if not api_key:
        raise RuntimeError("STRIPE_SECRET_KEY no configurada.")
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.delete(
            f"{STRIPE_API_BASE}/subscriptions/{subscription_id}",
            auth=(api_key, ""),
        )
    if r.status_code >= 400:
        raise RuntimeError(f"Stripe error {r.status_code}: {r.text[:500]}")
    return r.json()


# ── Verificación de firma de webhooks ─────────────────────────────────
def verify_webhook_signature(
    payload: bytes, sig_header: str, secret: str, tolerance: int = 300
) -> bool:
    """Valida la cabecera Stripe-Signature (esquema v1, HMAC-SHA256).

    No requiere el SDK: replica el algoritmo documentado por Stripe.
    """
    if not sig_header or not secret:
        return False
    ts: Optional[str] = None
    sigs: list[str] = []
    for part in sig_header.split(","):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        k = k.strip()
        if k == "t":
            ts = v.strip()
        elif k == "v1":
            sigs.append(v.strip())
    if not ts or not sigs:
        return False
    # Anti-replay
    try:
        if abs(time.time() - int(ts)) > tolerance:
            return False
    except ValueError:
        return False
    signed_payload = f"{ts}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)
